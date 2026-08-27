import logging
from collections import defaultdict

import pytz

from markupsafe import Markup

from odoo import models, fields, api, Command, _
from odoo.exceptions import UserError, ValidationError

from .toc_online_service import TocOnlineService

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    l10npt_vat_exempt_reason = fields.Many2one(
        "account.l10n_pt.vat.exempt.reason",
        string="VAT Exempt Reason", copy=False
    )

    toc_status = fields.Selection([
        ("draft", "Draft"),
        ("sent", "Sent"),
        ("error", "Error"),
    ], default="draft", string="TOConline Status", copy=False)

    toc_document_no = fields.Char("TOConline Document No", copy=False)
    toc_document_id = fields.Char("TOConline Document ID" , copy=False)
    toc_pdf_attached = fields.Boolean("TOC PDF Attached", default=False, copy=False)
    toc_communication_code = fields.Char("AT Communication Code", copy=False)
    toc_at_communication_status = fields.Char("AT Communication Status", copy=False, readonly=True)
    toc_at_state = fields.Selection([
        ("done", "Communicated"),
        ("error", "Failed"),
    ], string="AT Communication State", copy=False, readonly=True)
    use_license_plate = fields.Boolean(string='User License Plate')
    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehicle')

    def _log_toc_transmission(self, request_type, success, error_message=''):
        self.ensure_one()
        type_labels = {
            'GR': _('Guia de Remessa Send'),
            'GD': _('Guia de Devolução Send'),
            'GT': _('Guia de Transporte Send'),
            'at_communication': _('AT Communication'),
        }
        type_label = type_labels.get(request_type, request_type)
        status_label = _('Success') if success else _('Error')
        doc_ref = (self.toc_document_no if success else None) or self.name or '/'
        body = Markup("<b>%s</b><ul><li>%s: %s</li><li>%s: %s</li><li>%s: %s</li>") % (
            _("TOConline communication"),
            _("Type"), type_label,
            _("Document"), doc_ref,
            _("Status"), status_label,
        )
        if error_message:
            body += Markup("<li>%s: %s</li>") % (_("Error"), error_message)
        body += Markup("</ul>")
        # A transfer split off in this transaction is not visible to the audit cursor.
        with self.env.registry.cursor() as audit_cr:
            audit_env = api.Environment(audit_cr, self.env.uid, self.env.context)
            audited = audit_env['stock.picking'].browse(self.id).exists()
            if audited:
                audited.message_post(body=body)
                return
        self.message_post(body=body)

    # =====================================================
    # SEND GR / GT (Waybills)
    # =====================================================

    def _pre_action_done_hook(self):
        # A TOConline document covers a single stock owner.
        if not self.env.context.get("skip_owner_split"):
            pickings_to_split = self.filtered(lambda p: p._toc_needs_owner_split())
            if pickings_to_split:
                return pickings_to_split._action_generate_owner_split_wizard()
        return super()._pre_action_done_hook()

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            if not picking.company_id.toc_online_enabled or picking.state != "done":
                continue
            document_type = picking._toc_shipment_document_type()
            if document_type:
                picking._send_transport_doc_to_toconline(document_type=document_type)
        return res

    def _send_transport_doc_to_toconline(self, document_type="GR"):
        self.ensure_one()

        if self.toc_status == "sent":
            return

        if not self.name:
            raise UserError(_("Cannot send to TOConline: picking reference (external_reference) is not set."))

        # Internal movements are addressed to the company itself.
        if self.picking_type_code != "internal" and not self.partner_id:
            raise UserError(_("Picking has no partner."))

        parent_document_reference = None
        if document_type == "GD":
            if not self.return_id or not self.return_id.toc_document_no:
                raise UserError(_(
                    "The original delivery must have been sent to TOConline "
                    "before its return can be registered."
                ))
            parent_document_reference = self.return_id.toc_document_no

        service = TocOnlineService(self.company_id, self.env)

        lines = []
        for move in self.move_ids:
            done_qty = sum(move.move_line_ids.mapped("quantity"))
            if done_qty <= 0:
                continue

            product = move.product_id
            product_id = service.get_or_create_product(product)

            line_dict = {
                "item_type": "Product",
                "item_id": product_id,
                "item_code": product.default_code or product.name[:30],
                "description": product.display_name[:100],
                "quantity": done_qty,
                "unit_of_measure": "un",
                "unit_price": 0.0,
            }

            lines.append(line_dict)

        if not lines:
            return

        payload = self._prepare_gr_payload(
            service,
            lines,
            document_type=document_type,
            parent_document_reference=parent_document_reference,
        )

        try:
            response = service.send_document(payload)
        except Exception as e:
            self.toc_status = "error"
            self._log_toc_transmission(document_type, success=False, error_message=str(e))
            raise

        if response.status_code not in (200, 201):
            self.toc_status = "error"
            err = response.text or 'HTTP %s' % response.status_code
            self._log_toc_transmission(document_type, success=False, error_message=err)
            raise UserError(_("Error sending to TOConline: %s") % response.text)

        data = response.json()

        self.write({
            "toc_status": "sent",
            "toc_document_no": data.get("document_no"),
            "toc_document_id": data.get("id"),
        })
        self._log_toc_transmission(document_type, success=True)

        if self.toc_document_id:
            service.communicate_to_at(self, self.toc_document_id, document_type)
            self._download_and_attach_toc_pdf(service, document_type=document_type)

    def action_retry_at_communication(self):
        """Communicate the transfer to the AT again, and download a fresh PDF only if it succeeds."""
        self.ensure_one()
        if not self.toc_document_id:
            raise UserError(_("No TOConline document is linked to %s.") % self.display_name)

        document_type = self._toc_shipment_document_type()
        if not document_type:
            raise UserError(_("%s is not a transfer that TOConline documents.") % self.display_name)

        service = TocOnlineService(self.company_id, self.env)
        if not service.communicate_to_at(self, self.toc_document_id, document_type):
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "danger",
                    "title": _("AT communication failed"),
                    "message": _("See the chatter for the reason reported by TOConline."),
                    "sticky": True,
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }

        self.toc_pdf_attached = False
        self._download_and_attach_toc_pdf(service, document_type=document_type)

    def _is_delivery_return(self):
        self.ensure_one()
        return bool(
            self.return_id
            and self.return_id.picking_type_code == "outgoing"
            and self.picking_type_code == "incoming"
        )

    # =====================================================
    # STOCK OWNERSHIP (consignment)
    # =====================================================

    def _toc_done_move_lines(self):
        self.ensure_one()
        return self.move_line_ids.filtered(lambda ml: ml.quantity > 0)

    def _toc_stock_owner(self):
        """External owner of the stock being moved, empty when it is ours."""
        self.ensure_one()
        owners = self._toc_done_move_lines().owner_id
        return (owners - self.company_id.partner_id)[:1]

    def _toc_owner_groups(self):
        """Group the quantities being moved by the owner of the stock.

        :return: {owner record (empty when company-owned): stock.move.line recordset}
        """
        self.ensure_one()
        company_partner = self.company_id.partner_id
        groups = defaultdict(lambda: self.env["stock.move.line"])
        for line in self._toc_done_move_lines():
            owner = line.owner_id - company_partner
            groups[owner] |= line
        return groups

    def _toc_needs_owner_split(self):
        """Whether this transfer carries stock from more than one owner."""
        self.ensure_one()
        if not self.company_id.toc_online_enabled or self.picking_type_code != "outgoing":
            return False
        return len(self._toc_owner_groups()) > 1

    def _toc_shipment_document_type(self):
        """TOConline document code for this transfer: GR, GT or GD."""
        self.ensure_one()
        if self.picking_type_code == "outgoing":
            return "GT" if self._toc_stock_owner() else "GR"
        if self._is_delivery_return():
            return "GD"
        if self.picking_type_code == "internal":
            return "GT"
        return False

    def _action_generate_owner_split_wizard(self):
        return {
            "name": _("Split Transfer by Stock Owner"),
            "type": "ir.actions.act_window",
            "res_model": "toc.picking.owner.split.wizard",
            "view_mode": "form",
            "views": [(self.env.ref("toc_invoice.view_toc_picking_owner_split").id, "form")],
            "target": "new",
            "context": dict(self.env.context, default_pick_ids=[Command.set(self.ids)]),
        }

    def _toc_split_by_owner(self):
        """Split each transfer so it only carries stock from a single owner.

        :return: the newly created stock.picking records
        """
        new_pickings = self.env["stock.picking"]
        for picking in self:
            groups = picking._toc_owner_groups()
            if len(groups) <= 1:
                continue
            owners = [owner for owner in groups if owner]
            if len(owners) == len(groups):
                # Nothing company-owned: the first owner keeps the original transfer.
                owners = owners[1:]
            for owner in owners:
                new_pickings |= picking._toc_extract_owner_picking(owner, groups[owner])
        return new_pickings

    def _toc_extract_owner_picking(self, owner, move_lines):
        """Move ``move_lines``, which all belong to ``owner``, into a new transfer."""
        self.ensure_one()
        new_picking = self._create_backorder_picking()
        # The exemption reason is copy=False, but a split is the same shipment.
        new_picking.l10npt_vat_exempt_reason = self.l10npt_vat_exempt_reason
        if not owner.company_id or owner.company_id == self.company_id:
            new_picking.owner_id = owner

        original_moves = move_lines.move_id
        moves_to_extract = self.env["stock.move"]
        for move in original_moves:
            lines = move_lines.filtered(lambda ml: ml.move_id == move)
            fully_owned = lines == move.move_line_ids.filtered(lambda ml: ml.quantity > 0)
            fully_done = move.product_uom.compare(move.quantity, move.product_uom_qty) >= 0
            if fully_owned and fully_done:
                moves_to_extract |= move
                continue
            # Shared with another owner or leaving a backorder: peel off this owner's share.
            qty = sum(lines.mapped("quantity_product_uom"))
            new_move = self.env["stock.move"].create(move._split(qty))
            new_move.with_context(bypass_entire_pack=True)._action_confirm(
                merge=False, create_proc=False,
            )
            lines.write({"move_id": new_move.id})
            moves_to_extract |= new_move

        moves_to_extract.write({"picking_id": new_picking.id, "picked": True})
        moves_to_extract.move_line_ids.write({"picking_id": new_picking.id})
        # Reservation moved between moves, on both sides of the split.
        (original_moves | moves_to_extract)._recompute_state()
        self.message_post(body=_(
            "Transfer %(picking)s created for the stock owned by %(owner)s.",
            picking=new_picking._get_html_link(),
            owner=owner.display_name,
        ))
        return new_picking

    def _get_toc_shipment_partners(self):
        self.ensure_one()
        warehouse_partner = (
                self.picking_type_id.warehouse_id.partner_id
                or self.company_id.partner_id
        )
        partner = self.partner_id or self.company_id.partner_id
        if self.picking_type_code in ["incoming", "internal"]:
            return partner, warehouse_partner
        return warehouse_partner, partner


    @staticmethod
    def _zip_pt(zip_code):
        """Format a zip code to Portuguese format (XXXX-XXX)."""
        if not zip_code:
            return "0000-000"
        digits = ''.join(filter(str.isdigit, zip_code))
        if len(digits) >= 7:
            return f"{digits[:4]}-{digits[4:7]}"
        return "0000-000"

    def _get_toc_document_date(self, service, document_type):
        """Return a document date that respects TOConline chronology.
        """
        self.ensure_one()
        base_date = (
            self.scheduled_date.date()
            if self.scheduled_date
            else fields.Date.today()
        )
        doc_date = max(base_date, fields.Date.today())

        last_toc_date = service.get_last_document_date(document_type=document_type)
        if last_toc_date and last_toc_date > doc_date:
            doc_date = last_toc_date

        if doc_date > base_date:
            self.sudo().write({"scheduled_date": doc_date})

            _logger.warning(
                "Picking %s: adjusting TOC document date from %s to %s for chronology.",
                self.name, base_date, doc_date,
            )
            self.message_post(
                body=_(
                    "Scheduled date adjusted to %s to satisfy TOConline chronology."
                ) % doc_date,
            )
        return doc_date

    def _prepare_gr_payload(self, service, lines, document_type="GR", parent_document_reference=None):
        """Prepare the payload for TOConline."""
        self.ensure_one()
        is_internal = self.picking_type_code == "internal"
        # In an internal movement, the fiscal recipient (customer) is the company itself.
        # If outgoing, it's the customer (partner_id).
        customer_partner = self.company_id.partner_id if is_internal else self.partner_id
        # Loading / unloading derived from the picking's actual direction,
        # so returns (incoming) are not swapped relative to deliveries.
        from_partner, delivery_partner = self._get_toc_shipment_partners()
        doc_date = self._get_toc_document_date(service, document_type)

        current_datetime = fields.Datetime.now()
        loading_time = (
            self.scheduled_date
            if self.scheduled_date and self.scheduled_date >= current_datetime
            else current_datetime
        )

        tax_exemption_reason = None
        if self.l10npt_vat_exempt_reason:
            exemption_code = self.l10npt_vat_exempt_reason.code
            exemption_id = service.get_tax_exemption_reason_id(exemption_code)
            if not exemption_id:
                raise UserError(
                    _("Motivo de isenção '%s' não encontrado no TOConline.")
                    % exemption_code
                )
            tax_exemption_reason = exemption_id

        payload = {
            # ADDED: If internal, send as GT (Guia de Transporte), otherwise GR (Guia de Remessa)
            "document_type": document_type,
            "date": doc_date.strftime("%Y-%m-%d"),
            "external_reference": self.name,

            # Fiscal Customer Data (In case of internal, it's the company itself)
            "customer_business_name": customer_partner.name,
            "customer_tax_registration_number": customer_partner.vat or "999999990",
            "customer_address_detail": customer_partner.street or "",
            "customer_postcode": self._zip_pt(customer_partner.zip),
            "customer_city": customer_partner.city or "",
            "customer_country": customer_partner.country_id.code or "PT",

            # Loading Data
            "shipment_from_address_detail": from_partner.street or "",
            "shipment_from_postcode": self._zip_pt(from_partner.zip),
            "shipment_from_city": from_partner.city or "",
            "shipment_from_country": from_partner.country_id.code if from_partner.country_id else "PT",

            "operation_country": "PT",

            # Unloading Data (MANDATORY)
            "shipment_address_detail": delivery_partner.street or "",
            "shipment_city": delivery_partner.city or "",
            "shipment_postcode": self._zip_pt(delivery_partner.zip),
            "shipment_country": delivery_partner.country_id.code or "PT",
            "shipment_loading_time": pytz.utc.localize(loading_time).astimezone(
                pytz.timezone('Europe/Lisbon')
            ).strftime("%Y-%m-%dT%H:%M:%S%z"),

            "tax_exemption_reason_id": tax_exemption_reason,
            "lines": lines,
        }
        # Only a delivery names the owner of goods that are not ours.
        stock_owner = self._toc_stock_owner()
        if stock_owner and self.picking_type_code == "outgoing":
            payload["notes"] = _(
                "Goods owned by %(name)s (VAT %(vat)s)",
                name=stock_owner.name,
                vat=stock_owner.vat or "/",
            )[:400]
        if self.use_license_plate and self.vehicle_id and self.vehicle_id.license_plate:
            payload["vehicle_registration"] = self.vehicle_id.license_plate
        if parent_document_reference:
            payload["parent_document_reference"] = parent_document_reference
        return payload

    def _download_and_attach_toc_pdf(self, service, document_type):
        self.ensure_one()

        if self.toc_pdf_attached:
            return

        safe_name = self.name.replace("/", "_") if self.name else "picking"
        guia_subtype = {
            "GR": "Remessa", "GD": "Devolucao", "GT": "Transporte",
        }.get(document_type, document_type)
        filename = f"Guia_{guia_subtype}_{safe_name}.pdf"

        service.download_and_attach_pdf(
            self, self.toc_document_id, filename,
            message=_("%s PDF downloaded and attached.") % document_type,
        )
        self.write({"toc_pdf_attached": True})

        _logger.info("%s PDF attached to picking %s", document_type, self.name)

    @api.model
    def cron_retry_toc_pickings(self, batch_size=50):
        commit_progress = self.env['ir.cron']._commit_progress

        pending = self.env['stock.picking'].search([
            ('state', '=', 'done'),
            ('toc_status', 'in', ('draft', 'error')),
            ('company_id.toc_online_enabled', '=', True),
        ], limit=batch_size)
        commit_progress(remaining=len(pending))
        for picking in pending:
            try:
                document_type = picking._toc_shipment_document_type()
                if document_type:
                    picking._send_transport_doc_to_toconline(document_type=document_type)
                commit_progress(1)
            except Exception as e:
                _logger.error("TOConline cron picking retry failed for %s: %s", picking.name, e)
                self.env.cr.rollback()

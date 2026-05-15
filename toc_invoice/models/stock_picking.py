import logging
import pytz

from odoo import models, fields, api, _
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
    use_license_plate = fields.Boolean(string='User License Plate')
    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehicle')
    # =====================================================
    # SEND GR / GT (Waybills)
    # =====================================================

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            if not picking.company_id.toc_online_enabled or picking.state != "done":
                continue
            if picking.picking_type_code == "outgoing":
                picking._send_transport_doc_to_toconline(document_type="GR")
            elif picking._is_delivery_return():
                picking._send_transport_doc_to_toconline(
                    document_type=TOC_RETURN_DOC_TYPE,
                )
            company = picking.company_id
            # ADDED: 'internal' to the types that trigger the dispatch
            if picking.picking_type_code == "internal" and picking.state == "done" and company.toc_online_enabled:
                picking._send_delivery_to_toconline()
        return res

    def _send_transport_doc_to_toconline(self, document_type="GR"):
        self.ensure_one()

        if self.toc_status == "sent":
            return

        if not self.partner_id:
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

        response = service.send_document(payload)

        if response.status_code not in (200, 201):
            self.toc_status = "error"
            raise UserError(_("Error sending to TOConline: %s") % response.text)

        data = response.json()

        self.write({
            "toc_status": "sent",
            "toc_document_no": data.get("document_no"),
            "toc_document_id": data.get("id"),
        })

        if self.toc_document_id:
            self._download_and_attach_toc_pdf(service, document_type=document_type)

    def _is_delivery_return(self):
        self.ensure_one()
        return bool(
            self.return_id
            and self.return_id.picking_type_code == "outgoing"
            and self.picking_type_code == "incoming"
        )

    def _get_toc_shipment_partners(self):
        self.ensure_one()
        warehouse_partner = (
                self.picking_type_id.warehouse_id.partner_id
                or self.company_id.partner_id
        )
        if self.picking_type_code == "incoming":
            return self.partner_id, warehouse_partner
        return warehouse_partner, self.partner_id


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
        # The unloading address is the partner filled in the picking (so we know where the installation site is)
        # If none is provided, assume the company's address.
        delivery_partner = self.partner_id if self.partner_id else self.company_id.partner_id
        doc_date = self._get_toc_document_date(service, document_type)
        warehouse = self.picking_type_id.warehouse_id
        from_partner = warehouse.partner_id or self.company_id.partner_id

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
            "document_type": "GT" if is_internal else "GR",
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
        if self.use_license_plate and self.vehicle_id and self.vehicle_id.license_plate:
            payload["vehicle_registration"] = self.vehicle_id.license_plate
        return payload

    def _send_delivery_to_toconline(self):
        self.ensure_one()

        if self.toc_status == "sent":
            return

        is_internal = self.picking_type_code == "internal"

        # Allow internal movements without a strict partner_id (uses the company),
        # but require a partner for outgoing deliveries.
        if not is_internal and not self.partner_id:
            raise UserError(_("Delivery has no customer."))

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
                "unit_price": unit_price,
                "tax_code": tax_code,
                "tax_percentage": tax_percentage,
                "tax_country_region": tax_region,
            }

            lines.append(line_dict)

        if not lines:
            return

        payload = self._prepare_gr_payload(service, lines, document_type=document_type,
                                           parent_document_reference=parent_document_reference)
        response = service.send_document(payload)

        if response.status_code not in (200, 201):
            self.toc_status = "error"
            raise UserError(_("Error sending to TOConline: %s") % response.text)

        data = response.json()

        self.write({
            "toc_status": "sent",
            "toc_document_no": data.get("document_no"),
            "toc_document_id": data.get("id"),
        })

        if self.toc_document_id:
            self._download_and_attach_toc_pdf(service, document_type=document_type)


    def _communicate_to_at(self, service, toc_doc_id):
        at_data = service.communicate_to_at(toc_doc_id)
        if at_data:
            self.toc_communication_code = at_data.get("communication_code")
            self.message_post(body=_("AT Communication Code: %s") % self.toc_communication_code)


    def _download_and_attach_toc_pdf(self, service, document_type):
        self.ensure_one()

        if self.toc_pdf_attached:
            return

        safe_name = self.name.replace("/", "_") if self.name else "picking"
        guia_subtype = {"GR": "Remessa", "GD": "Devolucao"}.get(document_type, document_type)
        filename = f"Guia_{guia_subtype}_{safe_name}.pdf"

        service.download_and_attach_pdf(
            self, self.toc_document_id, filename,
            message=_("%s PDF downloaded and attached.") % document_type,
        )
        self.write({"toc_pdf_attached": True})

        _logger.info("%s PDF attached to picking %s", document_type, self.name)

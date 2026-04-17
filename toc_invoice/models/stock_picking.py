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
        string="VAT Exempt Reason",
    )

    toc_status = fields.Selection([
        ("draft", "Draft"),
        ("sent", "Sent"),
        ("error", "Error"),
    ], default="draft", string="TOConline Status")

    toc_document_no = fields.Char("TOConline Document No")
    toc_document_id = fields.Char("TOConline Document ID")
    toc_pdf_attached = fields.Boolean("TOC PDF Attached", default=False)
    toc_communication_code = fields.Char("AT Communication Code")


    # =====================================================
    # SEND GR
    # =====================================================

    def button_validate(self):
        for picking in self:
            if (
                picking.picking_type_code == "outgoing"
                and picking.company_id.toc_online_enabled
                and not picking.l10npt_vat_exempt_reason
            ):
                has_exempt_lines = False
                for move in picking.move_ids:
                    taxes = False
                    if move.sale_line_id:
                        taxes = move.sale_line_id.tax_ids.filtered(lambda t: t.type_tax_use == "sale")
                    if not taxes or any(round(t.amount, 2) == 0.0 for t in taxes):
                        has_exempt_lines = True
                        break
                if has_exempt_lines:
                    raise ValidationError(
                        _("A tax exemption reason must be provided.")
                    )
        res = super().button_validate()
        for picking in self:
            company = picking.company_id
            if picking.picking_type_code == "outgoing" and picking.state == "done" and company.toc_online_enabled:
                picking._send_delivery_to_toconline()
        return res


    @staticmethod
    def _zip_pt(zip_code):
        """Format a zip code to Portuguese format (XXXX-XXX)."""
        if not zip_code:
            return "0000-000"
        digits = ''.join(filter(str.isdigit, zip_code))
        if len(digits) >= 7:
            return f"{digits[:4]}-{digits[4:7]}"
        return "0000-000"

    def _prepare_gr_payload(self, service, lines):
        """Prepare the GR payload for TOConline. Override to customise addresses."""
        self.ensure_one()
        partner = self.partner_id

        doc_date = (
            self.scheduled_date.date()
            if self.scheduled_date
            else fields.Date.today()
        )

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

        return {
            "document_type": "GR",
            "date": doc_date.strftime("%Y-%m-%d"),
            "external_reference": self.name,

            "customer_business_name": partner.name,
            "customer_tax_registration_number": partner.vat or "999999990",
            "customer_address_detail": partner.street or "",
            "customer_postcode": partner.zip or "0000-000",
            "customer_city": partner.city or "",
            "customer_country": partner.country_id.code or "PT",

            "shipment_from_address_detail": from_partner.street or "",
            "shipment_from_postcode": self._zip_pt(from_partner.zip),
            "shipment_from_city": from_partner.city or "",
            "shipment_from_country": from_partner.country_id.code if from_partner.country_id else "PT",

            "operation_country": "PT",

            # DESCARGA (OBRIGATÓRIO GR)
            "shipment_address_detail": partner.street or "",
            "shipment_city": partner.city or "",
            "shipment_postcode": self._zip_pt(partner.zip),
            "shipment_country": partner.country_id.code or "PT",
            "shipment_loading_time": pytz.utc.localize(loading_time).astimezone(
                pytz.timezone('Europe/Lisbon')
            ).strftime("%Y-%m-%dT%H:%M:%S%z"),
            "tax_exemption_reason_id": tax_exemption_reason,
            "lines": lines,
        }

    def _send_delivery_to_toconline(self):
        self.ensure_one()

        if self.toc_status == "sent":
            return

        if not self.partner_id:
            raise UserError(_("Delivery has no customer."))

        service = TocOnlineService(self.company_id, self.env)

        lines = []
        for move in self.move_ids:
            done_qty = sum(move.move_line_ids.mapped("quantity"))
            if done_qty <= 0:
                continue

            product = move.product_id
            product_id = service.get_or_create_product(product)

            unit_price = (
                move.sale_line_id.price_unit
                if move.sale_line_id
                else product.list_price
            )

            sale_line = move.sale_line_id

            tax = (
                sale_line.tax_ids.filtered(lambda t: t.type_tax_use == "sale")[:1]
                if sale_line
                else product.taxes_id.filtered(lambda t: t.type_tax_use == "sale")[:1]
            )

            tax_code = "ISE"
            tax_percentage = 0.0
            tax_region = "PT"
            tax_exemption_reason = None


            if tax:
                tax_percentage = round(tax.amount or 0.0, 2)

                if tax_percentage == 23:
                    tax_code = "NOR"
                elif tax_percentage == 13:
                    tax_code = "INT"
                elif tax_percentage == 6:
                    tax_code = "RED"
                elif tax_percentage == 0:
                    tax_code = "ISE"

                    if self.l10npt_vat_exempt_reason:
                        tax_exemption_reason = self.l10npt_vat_exempt_reason.code
                    else:
                        raise UserError(
                            _("Linha '%s' com IVA 0%% precisa de motivo de isenção.")
                            % product.display_name
                        )
                else:
                    tax_code = "NOR"

                _logger.info(
                    "IVA aplicado: %s | %s%% | Código: %s",
                    tax.name,
                    tax_percentage,
                    tax_code,
                )


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

        payload = self._prepare_gr_payload(service, lines)

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
            self._download_and_attach_toc_pdf(service)


    def _communicate_to_at(self, service, toc_doc_id):
        at_data = service.communicate_to_at(toc_doc_id)
        if at_data:
            self.toc_communication_code = at_data.get("communication_code")
            self.message_post(body=_("AT Communication Code: %s") % self.toc_communication_code)


    def _download_and_attach_toc_pdf(self, service):
        self.ensure_one()

        if self.toc_pdf_attached:
            return

        service.download_and_attach_pdf(
            self, self.toc_document_id, f"Guia_{self.name}.pdf",
            message=_("GR PDF downloaded and attached."),
        )
        self.write({"toc_pdf_attached": True})

        _logger.info("GR PDF attached to picking %s", self.name)

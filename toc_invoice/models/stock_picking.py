import logging
import base64
import pytz
import requests

from odoo import models, fields, _
from odoo.exceptions import UserError
from markupsafe import Markup

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    toc_status = fields.Selection([
        ("draft", "Draft"),
        ("sent", "Sent"),
        ("error", "Error"),
    ], default="draft", string="TOConline Status", copy=False)

    toc_document_no = fields.Char("TOConline Document No", copy=False)
    toc_document_id = fields.Char("TOConline Document ID", copy=False)
    toc_pdf_attached = fields.Boolean("TOC PDF Attached", default=False, copy=False)
    toc_communication_code = fields.Char("AT Communication Code", copy=False)
    use_license_plate = fields.Boolean(string="Use License Plate")
    vehicle_id = fields.Many2one("fleet.vehicle", string="Vehicle")
    toc_online_enabled = fields.Boolean(related="company_id.toc_online_enabled")


    # =====================================================
    # SEND GR / GT / GD
    # =====================================================

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            if picking.state == "done" and picking.company_id.toc_online_enabled:
                if picking.picking_type_code == "outgoing":
                    picking._send_transport_doc_to_toconline(document_type="GR")
                elif picking.picking_type_code == "internal":
                    picking._send_transport_doc_to_toconline(document_type="GT")
                elif picking._is_delivery_return():
                    picking._send_transport_doc_to_toconline(document_type="GD")
        return res

    def _is_delivery_return(self):
        self.ensure_one()
        return bool(
            self.return_id
            and self.return_id.picking_type_code == "outgoing"
            and self.picking_type_code == "incoming"
        )

    def _get_toc_shipment_partners(self):
        """Return (from_partner, to_partner) for the TOC shipment payload."""
        self.ensure_one()
        warehouse_partner = (
            self.picking_type_id.warehouse_id.partner_id
            or self.company_id.partner_id
        )
        if self.picking_type_code == "incoming":
            # Return: goods travel from the customer back to the warehouse.
            return self.partner_id, warehouse_partner
        # Outgoing or internal: from the warehouse to the customer / company.
        return warehouse_partner, self.partner_id or self.company_id.partner_id

    @staticmethod
    def _zip_pt(zip_code):
        if not zip_code:
            return "0000-000"
        digits = "".join(filter(str.isdigit, zip_code))
        if len(digits) >= 7:
            return f"{digits[:4]}-{digits[4:7]}"
        return "0000-000"


    def _send_transport_doc_to_toconline(self, document_type):
        """Send a transport document (GR, GT, or GD) to TOConline.
        """
        self.ensure_one()

        if self.toc_status == "sent":
            return

        is_internal = document_type == "GT"
        is_return = document_type == "GD"

        if not is_internal and not self.partner_id:
            raise UserError(_("Picking has no partner."))

        parent_document_reference = None
        exempt_reason_source_order = self.sale_id  # GR default
        if is_internal:
            exempt_reason_source_order = False
        elif is_return:
            if not self.return_id or not self.return_id.toc_document_no:
                raise UserError(_(
                    "The original delivery must have been sent to TOConline "
                    "before its return can be registered."
                ))
            parent_document_reference = self.return_id.toc_document_no
            exempt_reason_source_order = self.return_id.sale_id

        toc_api = self.env["toc.api"]
        access_token = toc_api.get_access_token(company=self.company_id)
        if not access_token:
            raise UserError(_("Could not obtain TOConline access token."))

        lines = []
        for move in self.move_ids:
            done_qty = sum(move.move_line_ids.mapped("quantity"))
            if done_qty <= 0:
                continue

            product = move.product_id
            product_id = self.env["account.move"].get_or_create_product_in_toconline(access_token, product, company=self.company_id)

            if is_internal:
                unit_price = product.standard_price or product.list_price
                tax = product.taxes_id.filtered(lambda t: t.type_tax_use == "sale")[:1]
            else:
                sale_line = move.sale_line_id or (
                    is_return
                    and move.origin_returned_move_id
                    and move.origin_returned_move_id.sale_line_id
                )
                unit_price = sale_line.price_unit if sale_line else product.list_price
                tax = (
                    sale_line.tax_id.filtered(lambda t: t.type_tax_use == "sale")[:1]
                    if sale_line
                    else product.taxes_id.filtered(lambda t: t.type_tax_use == "sale")[:1]
                )

            tax_code = "ISE"
            tax_percentage = 0.0
            if tax:
                tax_percentage = round(tax.amount or 0.0, 2)
                tax_code = {23: "NOR", 13: "INT", 6: "RED", 0: "ISE"}.get(tax_percentage, "NOR")

            lines.append({
                "item_type": "Product",
                "item_id": product_id,
                "item_code": product.default_code or product.name[:30],
                "description": product.display_name[:100],
                "quantity": done_qty,
                "unit_of_measure": "un",
                "unit_price": unit_price,
                "tax_code": tax_code,
                "tax_percentage": tax_percentage,
                "tax_country_region": "PT",
            })

        if not lines:
            return

        tax_exemption_reason_id = None
        if exempt_reason_source_order and exempt_reason_source_order.l10npt_vat_exempt_reason:
            code = exempt_reason_source_order.l10npt_vat_exempt_reason.code
            tax_exemption_reason_id = toc_api.get_tax_exemption_reason_id(access_token, code, company=self.company_id)
            if not tax_exemption_reason_id:
                raise UserError(
                    _("Motivo de isenção '%s' não encontrado no TOConline.") % code
                )

        payload = self._prepare_gr_payload(
            lines,
            document_type=document_type,
            parent_document_reference=parent_document_reference,
            tax_exemption_reason_id=tax_exemption_reason_id,
        )

        response = toc_api.toc_request(
            method="POST",
            url=f"{self.company_id._get_toc_api_url()}/api/v1/commercial_sales_documents",
            payload=payload,
            access_token=access_token,
        )

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
            self._download_and_attach_toc_pdf(access_token, document_type=document_type)


    def _prepare_gr_payload(self, lines, document_type="GR",
                            parent_document_reference=None,
                            tax_exemption_reason_id=None):
        """Build the TOConline payload for a transport document (GR/GT/GD)."""
        self.ensure_one()
        is_internal = document_type == "GT"

        customer_partner = self.company_id.partner_id if is_internal else self.partner_id
        from_partner, to_partner = self._get_toc_shipment_partners()

        doc_date = (
            self.scheduled_date.date()
            if self.scheduled_date
            else fields.Date.today()
        )
        current_datetime = fields.Datetime.now()
        loading_time = (
            self.scheduled_date
            if self.scheduled_date and self.scheduled_date >= current_datetime
            else current_datetime
        )

        payload = {
            "document_type": document_type,
            "date": doc_date.strftime("%Y-%m-%d"),
            "external_reference": self.name,

            "customer_business_name": customer_partner.name,
            "customer_tax_registration_number": customer_partner.vat or "999999990",
            "customer_address_detail": customer_partner.street or "",
            "customer_postcode": self._zip_pt(customer_partner.zip),
            "customer_city": customer_partner.city or "",
            "customer_country": customer_partner.country_id.code or "PT",

            "shipment_from_address_detail": from_partner.street or "",
            "shipment_from_postcode": self._zip_pt(from_partner.zip),
            "shipment_from_city": from_partner.city or "",
            "shipment_from_country": from_partner.country_id.code if from_partner.country_id else "PT",

            "operation_country": "PT",

            "shipment_address_detail": to_partner.street or "",
            "shipment_city": to_partner.city or "",
            "shipment_postcode": self._zip_pt(to_partner.zip),
            "shipment_country": to_partner.country_id.code if to_partner.country_id else "PT",
            "shipment_loading_time": pytz.utc.localize(loading_time).astimezone(
                pytz.timezone("Europe/Lisbon")
            ).strftime("%Y-%m-%dT%H:%M:%S%z"),

            "tax_exemption_reason_id": tax_exemption_reason_id,
            "lines": lines,
        }
        if self.use_license_plate and self.vehicle_id.license_plate:
            payload["vehicle_registration"] = self.vehicle_id.license_plate
        if parent_document_reference:
            payload["parent_document_reference"] = parent_document_reference
        return payload


    def _communicate_to_at(self, access_token, toc_doc_id):
        """ Comunica o documento à Autoridade Tributária """
        company = self.company_id
        # Estes campos devem existir na configuração da empresa no seu módulo
        at_user = company.toc_at_user
        at_pass = company.toc_at_password  # Deve ser base64 conforme documentação

        if not at_user or not at_pass:
            _logger.warning("AT credentials missing, skipping communication for %s", self.name)
            return

        payload_at = {
            "data": {
                "type": "send_document_at_webservice",
                "id": toc_doc_id,
                "attributes": {
                    # "document_type": "GR",
                    # "entity_username": at_user,
                    # "entity_password": at_pass
                }
            }
        }

        response = self.env["toc.api"].toc_request(
            method="POST",
            url=f"{self.company_id._get_toc_api_url()}/api/send_document_at_webservice",
            payload=payload_at,
            access_token=access_token,
        )

        if response.status_code == 200:
            at_data = response.json().get("data", {}).get("attributes", {})
            self.toc_communication_code = at_data.get("communication_code")
            self.message_post(body=_("AT Communication Code: %s") % self.toc_communication_code)


    def _download_and_attach_toc_pdf(self, access_token, document_type="GR"):
        self.ensure_one()

        if self.toc_pdf_attached:
            return

        url_api = (
            f"{self.company_id._get_toc_api_url()}/api/url_for_print/"
            f"{self.toc_document_id}?filter[type]=Document&filter[copies]=1"
        )

        response = self.env["toc.api"].toc_request(
            method="GET",
            url=url_api,
            access_token=access_token,
        )

        if response.status_code != 200:
            raise UserError(_("Failed to get %s PDF URL from TOConline.") % document_type)

        try:
            url_data = response.json()["data"]["attributes"]["url"]
            pdf_url = f"{url_data['scheme']}://{url_data['host']}{url_data['path']}"
        except Exception as e:
            raise UserError(_("Error parsing PDF URL: %s") % str(e))

        pdf_response = requests.get(pdf_url)
        if pdf_response.status_code != 200:
            raise UserError(_("Failed to download %s PDF.") % document_type)

        safe_name = (self.name or "picking").replace("/", "_")
        # GR keeps its historical filename to preserve existing behavior.
        if document_type == "GR":
            attachment_name = f"Guia_{safe_name}.pdf"
        else:
            guia_subtype = {"GD": "Devolucao", "GT": "Transporte"}.get(document_type, document_type)
            attachment_name = f"Guia_{guia_subtype}_{safe_name}.pdf"

        attachment = self.env["ir.attachment"].create({
            "name": attachment_name,
            "res_model": "stock.picking",
            "res_id": self.id,
            "type": "binary",
            "datas": base64.b64encode(pdf_response.content),
            "mimetype": "application/pdf",
        })

        self.write({"toc_pdf_attached": True})

        self.message_post(
            body=Markup(_("%s PDF downloaded and attached.") % document_type),
            attachment_ids=[attachment.id],
        )

        _logger.info("%s PDF attached to picking %s", document_type, self.name)
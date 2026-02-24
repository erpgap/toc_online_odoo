import logging
import base64
import requests

from odoo import models, fields, _
from odoo.exceptions import UserError
from markupsafe import Markup

from odoo.addons.toc_invoice.utils import TOC_BASE_URL

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    toc_status = fields.Selection([
        ("draft", "Draft"),
        ("sent", "Sent"),
        ("error", "Error"),
    ], default="draft", string="TOConline Status")

    toc_document_no = fields.Char("TOConline Document No")
    toc_document_id = fields.Char("TOConline Document ID")
    toc_pdf_attached = fields.Boolean("TOC PDF Attached", default=False)
    toc_communication_code = fields.Char("AT Communication Code")


    from odoo import _, fields
    from odoo.exceptions import UserError
    from markupsafe import Markup
    import logging

    _logger = logging.getLogger(__name__)

    # =====================================================
    # VALIDATE DELIVERY → SEND TO TOCONLINE
    # =====================================================

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            company = picking.company_id
            toc_enabled = company.toc_online_client_id and company.toc_online_client_secret
            if picking.picking_type_code == "outgoing" and picking.state == "done" and toc_enabled:
                picking._send_delivery_to_toconline()
        return res

    # =====================================================
    # SEND GR
    # =====================================================

    def _send_delivery_to_toconline(self):
        self.ensure_one()

        if self.toc_status == "sent":
            return

        if not self.partner_id:
            raise UserError(_("Delivery has no customer."))

        toc_api = self.env["toc.api"]
        access_token = toc_api.get_access_token()

        if not access_token:
            raise UserError(_("Could not obtain TOConline access token."))

        move_model = self.env["account.move"]

        lines = []
        for move in self.move_ids_without_package:
            done_qty = sum(move.move_line_ids.mapped("quantity"))
            if done_qty <= 0:
                continue

            product = move.product_id
            product_id = move_model.get_or_create_product_in_toconline(access_token, product)

            unit_price = (
                move.sale_line_id.price_unit
                if move.sale_line_id
                else product.list_price
            )

            # IVA do produto
            tax = product.taxes_id[:1]

            tax_code = "NOR"
            tax_percentage = 23.0
            tax_region = "PT"

            if tax:
                tax_percentage = tax.amount or 23.0

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
                "tax_country_region": tax_region,
            })

        if not lines:
            return

        partner = self.partner_id

        doc_date = (
            self.scheduled_date.date()
            if self.scheduled_date
            else fields.Date.today()
        )

        warehouse = self.picking_type_id.warehouse_id
        from_partner = warehouse.partner_id or self.company_id.partner_id
        to_partner = self.partner_id

        loading_time = self.date_done or fields.Datetime.now()

        def zip_pt(zip_code):
            if not zip_code:
                return "0000-000"
            digits = ''.join(filter(str.isdigit, zip_code))
            if len(digits) >= 7:
                return f"{digits[:4]}-{digits[4:7]}"
            return "0000-000"

        payload = {
            "document_type": "GR",
            "date": doc_date.strftime("%Y-%m-%d"),
            "external_reference": self.name,

            "customer_business_name": partner.name,
            "customer_tax_registration_number": partner.vat or "999999990",
            "customer_address_detail": partner.street or "",
            "customer_postcode": partner.zip or "0000-000",
            "customer_city": partner.city or "",
            "customer_country": partner.country_id.code or "PT",

            "operation_country": "PT",
            "shipment_address_detail": to_partner.street or "",
            "shipment_city": to_partner.city or "",
            "shipment_postcode": zip_pt(to_partner.zip),
            "shipment_country": to_partner.country_id.code or "PT",

            "lines": lines,
        }

        response = toc_api.toc_request(
            method="POST",
            url=f"{TOC_BASE_URL}/api/v1/commercial_sales_documents",
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
            self._download_and_attach_toc_pdf(access_token)


    def _communicate_to_at(self, access_token, toc_doc_id):
        company = self.company_id
        at_user = company.toc_at_user
        at_pass = company.toc_at_password

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
            url=f"{TOC_BASE_URL}/api/send_document_at_webservice",
            payload=payload_at,
            access_token=access_token,
        )

        if response.status_code == 200:
            at_data = response.json().get("data", {}).get("attributes", {})
            self.toc_communication_code = at_data.get("communication_code")
            self.message_post(body=_("AT Communication Code: %s") % self.toc_communication_code)



    # =====================================================
    # DOWNLOAD PDF
    # =====================================================
    def _download_and_attach_toc_pdf(self, access_token):
        self.ensure_one()

        if self.toc_pdf_attached:
            return

        url_api = (
            f"{TOC_BASE_URL}/api/url_for_print/"
            f"{self.toc_document_id}?filter[type]=Document&filter[copies]=1"
        )

        response = self.env["toc.api"].toc_request(
            method="GET",
            url=url_api,
            access_token=access_token,
        )

        if response.status_code != 200:
            raise UserError(_("Failed to get GR PDF URL from TOConline."))

        try:
            url_data = response.json()["data"]["attributes"]["url"]
            pdf_url = f"{url_data['scheme']}://{url_data['host']}{url_data['path']}"
        except Exception as e:
            raise UserError(_("Error parsing PDF URL: %s") % str(e))

        pdf_response = requests.get(pdf_url)
        if pdf_response.status_code != 200:
            raise UserError(_("Failed to download GR PDF."))

        attachment = self.env["ir.attachment"].create({
            "name": f"Guia_{self.name}.pdf",
            "res_model": "stock.picking",
            "res_id": self.id,
            "type": "binary",
            "datas": base64.b64encode(pdf_response.content),
            "mimetype": "application/pdf",
        })

        self.write({"toc_pdf_attached": True})

        self.message_post(
            body=Markup(_("GR PDF downloaded and attached.")),
            attachment_ids=[attachment.id],
        )

        _logger.info("GR PDF attached to picking %s", self.name)
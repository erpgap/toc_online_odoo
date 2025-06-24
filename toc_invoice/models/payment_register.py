import requests
import json
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.addons.toc_invoice.utils import TOC_BASE_URL


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def action_create_payments(self):
        res = super().action_create_payments()
        for wizard in self:
            access_token = self.env['toc.api'].get_access_token()
            if not access_token:
                raise UserError(_("TOConline access token not found"))

            if not wizard.partner_id:
                raise UserError(_("Payment must have an associated partner"))

            if not wizard.amount:
                raise UserError(_("Payment amount cannot be 0"))

            partner = wizard.partner_id
            company = wizard.company_id
            currency = wizard.currency_id
            date = wizard.payment_date or fields.Date.today()

            journal_type = wizard.journal_id.type
            payment_mechanism = 'MO' if journal_type == 'cash' else 'TR' if journal_type == 'bank' else ''

            invoice_id = self.env.context.get('active_id')
            invoice = self.env['account.move'].browse(invoice_id)
            document_no = invoice.get_ID_invoice()


            doc_id = invoice.get_document_field_by_number(access_token, document_no, "id")
            user_id = invoice.get_document_field_by_number(access_token, document_no, "user_id")
            company_id = invoice.get_document_field_by_number(access_token, document_no, "company_id")
            customer_id = invoice.get_document_field_by_number(access_token, document_no, "customer_id")
            ammount = invoice.get_document_field_by_number(access_token, document_no, "gross_total")



            lines = [{
                "cashed_vat_amount": None,
                "gross_total": wizard.amount,
                "net_total": wizard.amount,
                "receivable_id": doc_id,
                "receivable_type": "Document",
                "received_value": wizard.amount,
            }]
            payload = {
                "company_id": company_id,
                "country_id": partner.country_id.id if partner.country_id else 1,
                "currency_conversion_rate": 1,
                "currency_id": currency.id,
                "customer_id": customer_id,
                "date": date.strftime("%Y-%m-%d"),
                "gross_total": wizard.amount,
                "lines": lines,
                "manual_registration_number": None,
                "manual_registration_series": None,
                "manual_registration_type": None,
                "net_total": wizard.amount,
                "observations": "",
                "payment_mechanism": payment_mechanism,
                "saft_import_id": None,
                "standalone": True,
                "third_party_id": None,
                "third_party_type": None,
                "user_id": user_id,
            }

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            endpoint = f"{TOC_BASE_URL}/api/v1/commercial_sales_receipts"
            response = requests.post(endpoint, json=payload, headers=headers, timeout=120)

            if response.status_code != 200:
                raise UserError(f"Error sending payment: {response.text}")

            toc_receipt_data = response.json()
            receipt_id = toc_receipt_data.get("id")

            if invoice:
                existing_ids = json.loads(invoice.toc_receipt_ids or "[]")
                if receipt_id not in existing_ids:
                    existing_ids.append(receipt_id)
                    invoice.write({'toc_receipt_ids': json.dumps(existing_ids)})

            self.env.cr.commit()


        return res

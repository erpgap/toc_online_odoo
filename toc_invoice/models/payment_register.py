import json

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .toc_online_service import TocOnlineService


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def action_create_payments(self):
        res = super().action_create_payments()
        for wizard in self.filtered(lambda w: w.company_id.toc_online_enabled):
            invoice_id = self.env.context.get('active_id')
            invoice = self.env['account.move'].browse(invoice_id)
            document_no = invoice.get_ID_invoice() if invoice else False

            if not document_no:
                continue

            if not wizard.partner_id:
                raise UserError(_("Payment must have an associated partner"))

            if not wizard.amount:
                raise UserError(_("Payment amount cannot be 0"))

            service = TocOnlineService(wizard.company_id, self.env)

            partner = wizard.partner_id
            currency = wizard.currency_id
            date = wizard.payment_date or fields.Date.today()

            journal_type = wizard.journal_id.type
            payment_mechanism = 'MO' if journal_type == 'cash' else 'TR' if journal_type == 'bank' else ''

            doc_id = service.get_document_field_by_number(document_no, "id")
            user_id = service.get_document_field_by_number(document_no, "user_id")
            company_id = service.get_document_field_by_number(document_no, "company_id")
            customer_id = service.get_document_field_by_number(document_no, "customer_id")
            amount = service.get_document_field_by_number(document_no, "gross_total")

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

            try:
                response = service.create_receipt(payload)
            except Exception as e:
                raise UserError(_("Error sending payment: %s") % str(e))

            toc_receipt_data = response.json()
            receipt_id = toc_receipt_data.get("id")

            if invoice:
                existing_ids = json.loads(invoice.toc_receipt_ids or "[]")
                if receipt_id not in existing_ids:
                    existing_ids.append(receipt_id)
                    invoice.write({'toc_receipt_ids': json.dumps(existing_ids)})

            self.env.cr.commit()

        return res

import requests
import json
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    base_url = 'https://api9.toconline.pt'

    def get_total_paid_from_toc_by_receivable_id(self, toc_receipt_id):
        access_token = self.env['ir.config_parameter'].sudo().get_param('toc_online.access_token')
        if not access_token:
            raise UserError("Token TOConline não definido.")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        endpoint = f"{self.base_url}/api/v1/commercial_sales_receipts"
        response = requests.get(endpoint, headers=headers, timeout=60)

        if response.status_code != 200:
            raise UserError(f"Erro ao obter recibo TOC {toc_receipt_id}: {response.text}")

        result = response.json()
        receipts = result if isinstance(result, list) else [result]

        total_paid = 0.0
        for receipt in receipts:
            for line in receipt.get("lines", []):
                receivable_id = line.get("receivable_id")
                received_value = line.get("received_value", 0.0)

                if receivable_id == toc_receipt_id:
                    print(f"Receivable ID: {receivable_id} | Valor recebido: {received_value}")
                    total_paid += received_value

        return total_paid

    def action_create_payments(self):

        res = super().action_create_payments()

        for wizard in self:
            print("Só para avisar que passei por aqui : ---------------------------------------------------------------")

            access_token = self.env['ir.config_parameter'].sudo().get_param('toc_online.access_token')
            if not access_token:
                raise UserError("Token de acesso TOConline não encontrado.")

            if not wizard.partner_id:
                raise UserError("O pagamento deve ter um parceiro associado.")

            if not wizard.amount:
                raise UserError("O valor do pagamento não pode ser 0.")

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

            endpoint = f"{self.base_url}/api/v1/commercial_sales_receipts"
            response = requests.post(endpoint, json=payload, headers=headers, timeout=120)

            if response.status_code != 200:
                raise UserError(f"Erro ao enviar pagamento: {response.text}")

            toc_receipt_data = response.json()
            receipt_id = toc_receipt_data.get("id")

            if invoice:
                existing_ids = json.loads(invoice.toc_receipt_ids or "[]")
                if receipt_id not in existing_ids:
                    existing_ids.append(receipt_id)
                    invoice.write({'toc_receipt_ids': json.dumps(existing_ids)})

            self.env.cr.commit()


            print("este é o id do recebido do tocOnline  +++++++++++++++++++++++++++++++++++ " , receipt_id)
            print("aqui vamos fazer a comparação engtre o valor do toc e o valor a pagar no odoo")
            total = self.get_total_paid_from_toc_by_receivable_id(doc_id)
            print("este é o total do toc : ", total)
            print("este 'total do odoo introduzido :", wizard.amount)
            print("este 'total do misterio :", wizard.source_amount)
            print("este 'total do misterio 2222:", wizard.source_amount_currency)
            print("total da fatura : ", ammount)

            print("---------terminar---------------")
            print("-------o total de pagamentos é este ----------------------")
            print(total)
            print("-----------------------------------------------------------")

            aux = ammount - total
            print("falta pagar isto de acordo com o toc ", aux)
            print("Falta pagar isto de acordor com o odoo :", wizard.source_amount_currency)

        return res

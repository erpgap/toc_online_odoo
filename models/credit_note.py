import json
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class CreditNote(models.Model):
    _inherit = 'credit.note'

    def action_send_credit_note_to_toconline(self):
        """
        Envia uma Nota de Crédito para o TOConline, referenciando a fatura original.
        """

        for record in self:

            if record.toc_status != 'sent':
                raise UserError("Esta nota de crédito já foi enviada para o TOConline.")
            if record.state != 'posted':
                raise UserError("Apenas notas de crédito publicadas podem ser enviadas.")
            #if not record.reversed_entry_id:
             #   raise UserError("A nota de crédito precisa estar associada a uma fatura para ser enviada.")


            print("aiiiiiiiiiiiiiiiiiiiiii")
            access_token1 = self.env['ir.config_parameter'].sudo().get_param('toc_online.access_token')
            client_id1 = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_id')

            print(f"este é o meu access tokennnnnnnnnnnnnnnnn {access_token1} e o meu clientIDDDDDDDDDDDDDDDDDDDDDDDDDD {client_id1}")

            document_no = self.env['account.move'].get_ID_invoice()

            print(f"este é o numeroo da faturaaaaaaaaaaaaaaa {document_no}")
            original_invoice = record.reversed_entry_id  # Fatura original associada
            if not original_invoice.toc_invoice_url:
                raise UserError("A fatura original não possui um ID no TOConline.")

            # Obter token de acesso
            access_token = self.get_access_token()
            if not access_token:
                raise UserError("Não foi possível obter o token de acesso.")


            print(f"este é o token que esta a ser lido da credit note {access_token}")
            # Obter detalhes do cliente
            partner = record.partner_id
            customer_id = self.get_or_create_customer_in_toconline(access_token, partner)

            # Buscar taxas de IVA
            state_company = self.getStateCompany()
            region_map = {"Madeira": "PT-MA", "Açores": "PT-AC", "Continente": "PT"}
            tax_region = region_map.get(state_company, "PT")
            taxes_data = self.get_taxes_from_toconline(access_token)
            filtered_taxes = [tax for tax in taxes_data if tax["attributes"]["tax_country_region"] == tax_region]

            # Construir linhas do documento
            lines = []
            for line in record.invoice_line_ids:
                product_id = self.get_or_create_product_in_toconline(access_token, line.product_id)
                tax_percentage = line.tax_ids[0].amount if line.tax_ids else 0
                tax_code = self.get_tax_code(tax_percentage, tax_region, filtered_taxes)

                lines.append({
                    "item_id": product_id,
                    "item_code": line.product_id.default_code,
                    "description": line.product_id.name,
                    "quantity": line.quantity,
                    "unit_price": line.price_unit * -1,  # Valores negativos para nota de crédito
                    "tax_code": tax_code,
                    "item_type": "Product",
                    "exemption_reason": None,
                })

            # Configuração do payload
            payload = {
                "document_type": "NC",  # Nota de Crédito
                "parent_document_reference": original_invoice.name,  # Fatura associada (referência)
                "date": record.invoice_date.strftime("%Y-%m-%d") if record.invoice_date else "",
                "customer_tax_registration_number": partner.vat or "",
                "customer_business_name": partner.name,
                "customer_address_detail": partner.street or "",
                "customer_postcode": partner.zip or "",
                "customer_city": partner.city or "",
                "customer_country": tax_region,
                "due_date": record.invoice_date_due.strftime("%Y-%m-%d") if record.invoice_date_due else "",
                "payment_mechanism": "MO",
                "vat_included_prices": False,
                "operation_country": tax_region,
                "currency_iso_code": record.currency_id.name,
                "currency_conversion_rate": 1.0,
                "retention": 0,
                "retention_type": "IRS",
                "apply_retention_when_paid": False,
                "notes": f"Nota de crédito referente à fatura: {original_invoice.name}",
                "lines": lines,
            }

            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
            response = requests.post(f"{self.base_url}/api/v1/commercial_sales_documents", json=payload,
                                     headers=headers)

            print(payload)
            if response.status_code != 200:
                raise UserError(f"Erro ao enviar a nota de crédito. Resposta: {response.text}")

            # Atualiza o status da nota de crédito e pega o número do documento
            record.toc_status = 'sent'
            document_no = response.json().get('document_no', '')  # Recupera o número do documento
            record.toc_document_no = document_no  # Armazena o número do documento no campo customizado
            record.toc_invoice_url = response.json().get('invoice_url', '')  # URL da fatura gerada
            return True

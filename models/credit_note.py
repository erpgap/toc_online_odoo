import json
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class CreditNote(models.Model):
    _inherit = 'account.move'

    toc_status_credit_note = fields.Selection([
        ('draft', 'Rascunho'),
        ('sent', 'Enviado'),
        ('error', 'Erro')
    ], string="Status TOConline", default='draft')

    def get_document_lines(self,base_url, access_token, document_no):
        """
        Obtém as linhas de um documento de vendas a partir da API TOConline.

        :param base_url: URL base da API TOConline
        :param access_token: Token de autenticação Bearer
        :param document_no: Número do documento a ser consultado
        :return: Lista de linhas do documento ou None em caso de erro
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        url = f"{base_url}/api/v1/commercial_sales_documents?filter[document_no]={document_no}"

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()  # Lança um erro para status >= 400
            data = response.json()

            # Se a resposta for uma lista, pegamos o primeiro item (se existir)
            if isinstance(data, list) and len(data) > 0:
                data = data[0]  # Pegamos o primeiro dicionário da lista

            # Garantimos que data é um dicionário antes de chamar `.get()`
            if isinstance(data, dict):
                return data
            else:
                print("Erro: a resposta da API não contém um dicionário válido.")
                return None

        except requests.exceptions.RequestException as e:
            print(f"Erro ao conectar à API: {e}")
            return None

    def get_document_lines_only(self , base_url, access_token, document_no):
        """
        Obtém as linhas de um documento de vendas a partir da API TOConline.

        :param base_url: URL base da API TOConline
        :param access_token: Token de autenticação Bearer
        :param document_no: Número do documento a ser consultado
        :return: Lista de linhas do documento ou None em caso de erro
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        url = f"{base_url}/api/v1/commercial_sales_documents?filter[document_no]={document_no}"

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()  # Lança um erro para status >= 400
            data = response.json()

            # Se a resposta for uma lista, pegamos o primeiro item (se existir)
            if isinstance(data, list) and len(data) > 0:
                data = data[0]  # Pegamos o primeiro dicionário da lista

            # Garantimos que data é um dicionário antes de chamar `.get()`
            if isinstance(data, dict):
                # Retorna a parte das linhas (campo 'lines')
                return data.get("lines", [])
            else:
                print("Erro: a resposta da API não contém um dicionário válido.")
                return None

        except requests.exceptions.RequestException as e:
            print(f"Erro ao conectar à API: {e}")
            return None

    def action_send_credit_note_to_toconline(self):
        """
        Envia uma Nota de Crédito para o TOConline, referenciando a fatura original.
        """
        for record in self:
            if record.toc_status != 'sent':
                raise UserError(
                    "É necessário enviar primeiro a fatura para o TOConline e depois proceder à criação da nota de crédito.")
            if record.state != 'posted':
                raise UserError("Apenas notas de crédito publicadas podem ser enviadas.")
            if record.toc_status_credit_note == 'sent':
                raise UserError("Já foi enviada uma nota de crédito para o TOConline.")

            # Dados de configuração
            access_token = self.env['ir.config_parameter'].sudo().get_param('toc_online.access_token')
            if not access_token:
                raise UserError("Token de acesso não configurado.")

            base_url = record.get_base_url()
            invoice_toc_document_no = record.get_ID_invoice()
            if not invoice_toc_document_no:
                raise UserError("A fatura original não possui um ID no TOConline.")

            # Obter dados do documento original
            document_data = self.get_document_lines(base_url, access_token, invoice_toc_document_no)
            if not document_data:
                raise UserError("Não foi possível obter os detalhes da fatura original.")

            # Dados do cliente
            customer_tax_registration_number = document_data.get("customer_tax_registration_number")
            customer_business_name = document_data.get("customer_business_name")
            customer_address_detail = document_data.get("customer_address_detail")
            customer_postcode = document_data.get("customer_postcode")
            customer_city = document_data.get("customer_city")

            # Determinar região fiscal
            state_company = self.getStateCompany()
            region_map = {"Madeira": "PT-MA", "Açores": "PT-AC", "Continente": "PT"}
            tax_region = region_map.get(state_company, "PT")

            # Buscar taxas (caso precise de validação)
            taxes_data = self.get_taxes_from_toconline(access_token)
            filtered_taxes = [tax for tax in taxes_data if tax["attributes"]["tax_country_region"] == tax_region]

            # Preparar as linhas da nota de crédito
            lines = []
            for line in document_data.get("lines", []):
                lines.append({
                    "item_id": line.get("item_id"),
                    "item_code": line.get("item_code"),
                    "description": line.get("description"),
                    "quantity": line.get("quantity", 0),
                    "unit_price": line.get("unit_price", 0),
                    "tax_code": line.get("tax_code", "INT"),
                    "item_type": line.get("item_type", "Product"),
                    "exemption_reason": line.get("exemption_reason"),
                })

            # Montar payload
            payload = {
                "document_type": "NC",
                "parent_document_reference": invoice_toc_document_no,
                "date": record.invoice_date.strftime("%Y-%m-%d") if record.invoice_date else "",
                "due_date": record.invoice_date_due.strftime("%Y-%m-%d") if record.invoice_date_due else "",
                "customer_tax_registration_number": customer_tax_registration_number or "",
                "customer_business_name": customer_business_name,
                "customer_address_detail": customer_address_detail or "",
                "customer_postcode": customer_postcode or "",
                "customer_city": customer_city or "",
                "customer_tax_country_region": tax_region,
                "customer_country": tax_region,
                "payment_mechanism": "MO",
                "vat_included_prices": False,
                "operation_country": tax_region,
                "currency_iso_code": record.currency_id.name,
                "currency_conversion_rate": 1.0,
                "retention": 0,
                "retention_type": "IRS",
                "apply_retention_when_paid": False,
                "notes": f"Nota de crédito referente à fatura: {invoice_toc_document_no}",
                "lines": lines,
            }

            # Enviar requisição para TOConline
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
            response = requests.post(f"{base_url}/api/v1/commercial_sales_documents", json=payload, headers=headers)

            if response.status_code != 200:
                record.toc_status_credit_note = 'error'
                raise UserError(f"Erro ao enviar a nota de crédito. Resposta: {response.text}")

            # Sucesso
            response_data = response.json()
            record.toc_status_credit_note = 'sent'
            record.toc_document_no = response_data.get('document_no', '')
            record.toc_invoice_url = response_data.get('invoice_url', '')

        return True

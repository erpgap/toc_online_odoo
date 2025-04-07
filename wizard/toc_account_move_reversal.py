from odoo import models, fields, api
from odoo.exceptions import UserError
import requests


class CreditNoteWizard(models.TransientModel):
    _name = 'credit.note.wizard'
    _description = 'Wizard para Envio de Nota de Crédito'

    invoice_id = fields.Many2one('account.move', string="Fatura Original", required=True)
    toc_document_no = fields.Char(string="Número do Documento TOConline", readonly=True)

    # Dados do produto diretamente no wizard
    item_code = fields.Char(string="Código do Produto")
    description = fields.Char(string="Descrição")
    quantity = fields.Float(string="Quantidade", default=1.0)
    unit_price = fields.Float(string="Preço Unitário")
    tax_percentage = fields.Float(string="IVA (%)")
    tax_code = fields.Char(string="Código de IVA")

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        invoice_id = self.env.context.get('active_id')

        if invoice_id:
            invoice = self.env['account.move'].browse(invoice_id)
            res.update({
                'invoice_id': invoice.id,
                'toc_document_no': invoice.toc_document_no,
            })

            # Pré-preenchimento com a primeira linha de produto (se houver)
            if invoice.invoice_line_ids:
                first_line = invoice.invoice_line_ids.filtered(lambda l: l.product_id)[:1]
                if first_line:
                    line = first_line[0]
                    res.update({
                        'item_code': line.product_id.default_code or '',
                        'description': line.name or '',
                        'quantity': line.quantity,
                        'unit_price': line.price_unit,
                        'tax_percentage': sum(line.tax_ids.mapped('amount')) if line.tax_ids else 0.0,
                        'tax_code': ','.join(filter(None, line.tax_ids.mapped('description') or line.tax_ids.mapped('name')))
                    })

        return res


    def action_confirm(self):

        print("o valor que esta nesta variavel é :  " , self.tax_percentage)

        self.ensure_one()

        if not self.invoice_id or not self.invoice_id.toc_document_no:
            raise UserError("A fatura original precisa ter sido enviada para o TOConline.")

        access_token = self.env['ir.config_parameter'].sudo().get_param('toc_online.access_token')
        if not access_token:
            raise UserError("Access token do TOConline não encontrado.")

        url_base = self.invoice_id.get_base_url()
        invoice_toc_document_no = self.invoice_id.toc_document_no

        # Dados do cliente (podias também extrair de self.invoice_id.partner_id)
        document_data = self.invoice_id.get_document_lines(url_base, access_token, invoice_toc_document_no)

        tax_region = self.invoice_id.getStateCompany()
        region_map = {"Madeira": "PT-MA", "Açores": "PT-AC", "Continente": "PT"}
        tax_region = region_map.get(tax_region, "PT")

        print("vamos agora tambem ver qual a taxa registation ",tax_region)
        # Verificar se a taxa de IVA foi preenchida corretamente
        iva_percentage = self.tax_percentage if self.tax_percentage else 0.0
        """if iva_percentage == 0.0:
            # Tentando obter a taxa de IVA da primeira linha de fatura (caso não tenha sido preenchido)
            first_line = self.invoice_id.invoice_line_ids.filtered(lambda l: l.product_id)
            if first_line:
                # Assumindo que a primeira linha tem pelo menos um imposto
                iva_percentage = first_line[0].tax_ids[0].amount if first_line[0].tax_ids else 0.0
            if iva_percentage == 0.0:
                raise UserError("A taxa de IVA não foi preenchida corretamente.")
"""
        # Construir o payload
        payload = {
            "document_type": "NC",
            "parent_document_reference": invoice_toc_document_no,
            "date": self.invoice_id.invoice_date.strftime("%Y-%m-%d") if self.invoice_id.invoice_date else "",
            "due_date": self.invoice_id.invoice_date_due.strftime("%Y-%m-%d") if self.invoice_id.invoice_date_due else "",

            "customer_tax_registration_number": document_data.get("customer_tax_registration_number"),
            "customer_business_name": document_data.get("customer_business_name"),
            "customer_address_detail": document_data.get("customer_address_detail"),
            "customer_postcode": document_data.get("customer_postcode"),
            "customer_city": document_data.get("customer_city"),
            "customer_tax_country_region": tax_region,
            "customer_country": tax_region,
            "payment_mechanism": "MO",
            "vat_included_prices": False,
            "operation_country": tax_region,
            "currency_iso_code": self.invoice_id.currency_id.name,
            "currency_conversion_rate": 1.0,
            "retention": 0,
            "retention_type": "IRS",
            "apply_retention_when_paid": False,
            "notes": f"Nota de crédito referente à fatura: {invoice_toc_document_no}",
            "lines": [{
                "item_id": None,  # Se necessário, coloque o ID do produto, caso exista
                "item_code": self.item_code,
                "description": self.description,
                "quantity": self.quantity,
                "unit_price": self.unit_price,
                "tax_percentage": iva_percentage,  # Garantir que a taxa de IVA esteja correta
                #"tax_code": self.tax_code or "INT",
                # Defina o código de IVA, se não preenchido, use 'INT' (internacional)
                "item_type": "Product",
                "exemption_reason": None,
            }],
        }

        print(payload)
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
        response = requests.post(f"{url_base}/api/v1/commercial_sales_documents", json=payload, headers=headers)



        if response.status_code != 200:
            raise UserError(f"Erro ao enviar nota de crédito: {response.text}")

        # Atualizar estado na fatura
        self.invoice_id.write({
            'toc_status_credit_note': 'sent',
            'toc_document_no': response.json().get('document_no'),
            'toc_invoice_url': response.json().get('invoice_url'),
        })

        return {'type': 'ir.actions.act_window_close'}



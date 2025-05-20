from odoo import models, api, fields
from odoo.exceptions import UserError
import logging
from odoo.addons.toc_invoice.utils import TOC_BASE_URL
import requests

_logger = logging.getLogger(__name__)

class InvoiceSync(models.Model):
    _name = 'invoice.sync'
    _description = 'Sync Invoices from TOConline'

    @api.model
    def sync_invoices_from_toc(self):
        """Synchronization of invoices existing in TOCOnline and not in odoo"""

        company = self.env['res.company'].browse(2)
        self = self.with_company(company).sudo()

        empresa_id = self.env.company.id
        print("Empresa forçada com ID:", empresa_id)

        access_token = self.env['toc.api'].get_access_token()
        if not access_token:
            raise UserError("TOConline access token not found.")

        url = f"{TOC_BASE_URL}/api/v1/commercial_sales_documents?filter[document_type]=FT&sort=-date"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                raise UserError(f"Error communicating with TOConline: {response.status_code} - {response.text}")

            documents = response.json()
            if not isinstance(documents, list):
                raise UserError("Unexpected format in TOConline response.")

            toc_ft_docs = [
                doc for doc in documents
                if doc.get("document_type") == "FT" and doc.get("document_no") and doc.get("id")
            ]

            toc_doc_nos = [doc["document_no"] for doc in toc_ft_docs]

            existing_invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('toc_document_no', '!=', False),
                ('company_id', '=', 2),
            ])
            existing_toc_nos = set(existing_invoices.mapped('toc_document_no'))

            toc_not_in_odoo = [doc for doc in toc_ft_docs if doc["document_no"] not in existing_toc_nos]

            print("=== Documents already in ODOO (%d) ===" % len(existing_toc_nos))
            for doc_no in existing_toc_nos:
                print("Present in Odoo: %s" % doc_no)

            print("=== MISSING DOCUMENTS (%d) ===" % len(toc_not_in_odoo))
            for doc in toc_not_in_odoo:
                print("Missing in Odoo: %s | customer_id: %s" % (doc["document_no"], doc.get("customer_id")))

            for doc in toc_not_in_odoo:
                try:
                    self.create_invoice_in_odoo(doc)
                except Exception as e:
                    _logger.error("Error creating invoice %s: %s", doc.get('document_no'), str(e))

        except Exception as e:
            _logger.error("Error during synchronization: %s", str(e), exc_info=True)
            raise UserError(f"Error: {str(e)}")

    def create_invoice_in_odoo(self, toc_document_data):

        toc_document_id = toc_document_data.get('id')
        document_no = toc_document_data.get('document_no')
        status = toc_document_data.get('status')
        tax_reason = toc_document_data.get('tax_exemption_reason_id')

        lines = toc_document_data.get('lines', [])
        if not lines:
            raise UserError(f"Fatura {document_no} não contém linhas.")

        line = lines[0]
        quantity = line.get("quantity")
        unit_price = line.get("unit_price")
        tax_percentage = line.get("tax_percentage")
        codeP = line.get("item_code")

        print("Status da fatura:", status)
        print("Quantidade:", quantity)
        print("Preço unitário:", unit_price)
        print("Taxa IVA (%):", tax_percentage)
        print("Motivo isenção:", tax_reason)

        toc_document = self._get_toc_document_by_id(toc_document_id)
        if not toc_document:
            raise UserError(f"Fatura {document_no} não encontrada na TOConline.")

        toc_client_id = toc_document.get('customer_id')
        partner = self.env['res.partner'].search([('toc_online_id', '=', toc_client_id)], limit=1)
        if not partner:
            raise UserError(f"Cliente com TOConline ID {toc_client_id} não encontrado no Odoo.")

        product = self.env['product.product'].search([('default_code', '=', codeP)], limit=1)
        if not product:
            raise UserError(f"Produto com código {codeP} não encontrado no Odoo.")

        toc_company_id = toc_document.get('company_id')
        company = self.env['res.company'].search([('toc_company_id', '=', toc_company_id)], limit=1)
        if not company:
            _logger.warning(f"Empresa com TOC ID {toc_company_id} não encontrada. Usando empresa padrão.")
            company = self.env['res.company'].browse(2)  #

        self = self.with_company(company)

        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('company_id', '=', 2)
        ], limit=1)
        if not journal:
            raise UserError(f"Nenhum diário de vendas encontrado para a empresa {company.name}.")

        tax_percentage_float = float(tax_percentage)

        tax = self.env['account.tax'].search([
            ('amount', '>=', tax_percentage_float - 0.01),
            ('amount', '<=', tax_percentage_float + 0.01),
            ('type_tax_use', '=', 'sale'),
            ('company_id', '=',2),
            '|',
            ('country_id', '=', False),
            ('country_id', '=', company.country_id.id)
        ], limit=1)

        if not tax:
            if not tax_reason:
                raise UserError(
                    f"A fatura {document_no} tem taxa de IVA 0% mas nenhum motivo de isenção foi fornecido."
                )
            _logger.warning(f"Nenhum imposto encontrado com {tax_percentage}%. A linha será criada sem imposto.")
            tax_ids_for_line = []
        else:
            tax_ids_for_line = [(6, 0, [tax.id])]

        invoice_line_vals = {
            'product_id': product.id,
            'name': toc_document_data.get('description'),
            'quantity': quantity,
            'price_unit': unit_price,
            'tax_ids': tax_ids_for_line,
        }

        print("--------------------", toc_document_data.get('tax_exemption_reason_id'))
        toc_status_finalized = None
        if status == 1:
            toc_status_finalized = 'sent'
        elif status == 4:
            toc_status_finalized = 'cancelled'

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': toc_document_data.get('date'),
            'invoice_date_due': toc_document_data.get('due_date'),
            'company_id': 2,
            'l10npt_vat_exempt_reason': toc_document_data.get('tax_exemption_reason_id'),
            'invoice_line_ids': [(0, 0, invoice_line_vals)],
            'toc_document_no': document_no,
            'toc_status': toc_status_finalized,
            'toc_document_id': toc_document_id
        }

        print("Dados da fatura a ser criada:", invoice_vals)
        invoice = self.env['account.move'].create(invoice_vals)
        invoice.action_post()

        return invoice

    def _get_toc_document_by_id(self, toc_document_id):
        access_token = self.env['toc.api'].get_access_token()
        url = f"{TOC_BASE_URL}/api/v1/commercial_sales_documents/{toc_document_id}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                return response.json()
            else:
                _logger.error(f"Erro ao buscar documento TOC ID {toc_document_id}: {response.text}")
                return None
        except Exception as e:
            _logger.error(f"Erro ao conectar à TOConline para documento ID {toc_document_id}: {str(e)}")
            return None

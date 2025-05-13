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

        access_token = self.env['ir.config_parameter'].sudo().get_param('toc_online.access_token')

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
                ('toc_document_no', '!=', False)
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

    def _map_toc_tax_to_odoo_tax(self, tax_code, tax_percentage, company):
        """Mapeia o imposto TOC para o imposto do Odoo"""
        Tax = self.env['account.tax']

        if tax_percentage == 0:
            tax = Tax.search([
                ('amount', '=', 0),
                ('type_tax_use', '=', 'sale'),
                ('company_id', '=', company.id),
            ], limit=1)
            return tax

        tax = Tax.search([
            ('amount', '=', tax_percentage),
            ('type_tax_use', '=', 'sale'),
            ('company_id', '=', company.id),
        ], limit=1)

        if not tax:
            _logger.warning(f"Não encontrado imposto com taxa {tax_percentage}% no Odoo (empresa {company.name})")
        return tax

    def create_invoice_in_odoo(self, toc_document_data):
        toc_document_id = toc_document_data.get('id')
        document_no = toc_document_data.get('document_no')

        toc_document = self._get_toc_document_by_id(toc_document_id)
        if not toc_document:
            raise UserError(f"Invoice {document_no} not found in TOConline.")

        toc_client_id = toc_document.get('customer_id')
        partner_id = self.env['res.partner'].search([('toc_online_id', '=', toc_client_id)], limit=1)
        if not partner_id:
            raise UserError(f"Client TOConline ID {toc_client_id} not found in Odoo.")

        company = self.env['res.company'].browse(2)
        _logger.info(f"Forçando empresa com ID = {company.id} e nome = {company.name}")

        if company:
            print(">>> Empresa encontrada:", company.name, "| ID:", company.id, "| TOC ID:", company.toc_company_id)
        else:
            company = self.env.company
            print(">>> Empresa padrão usada:", company.name, "| ID:", company.id)

        self = self.with_company(company)

        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('company_id', '=', company.id)
        ], limit=1)

        if not journal:
            raise UserError(f"No sales journals found for company {company.name}.")

        currency_code = toc_document.get('currency_iso_code', 'EUR')
        currency = self.env['res.currency'].search([('name', '=', currency_code)], limit=1)
        if not currency:
            raise UserError(f"Moeda '{currency_code}' não encontrada no Odoo.")

        invoice_lines = []
        for line in toc_document.get('lines', []):
            print("Tax Code:", line.get('tax_code'))
            print("Tax Percentage:", line.get('tax_percentage'))

            product = self.env['product.product'].search([('default_code', '=', line.get('item_code'))], limit=1)
            if not product:
                product = self.env['product.product'].create({
                    'name': line.get('description', 'Produto TOC'),
                    'default_code': line.get('item_code'),
                    'type': 'product',
                    'detailed_type': 'product',
                    'sale_ok': True,
                    'purchase_ok': False,
                })

            tax = self._map_toc_tax_to_odoo_tax(
                line.get('tax_code'),
                line.get('tax_percentage'),
                company
            )
            tax_ids = [(6, 0, [tax.id])] if tax else []

            print("Tax IDs aplicados:", tax_ids)

            invoice_lines.append((0, 0, {
                'product_id': product.id,
                'name': line.get('description', 'Produto TOC'),
                'quantity': line.get('quantity', 1),
                'price_unit': line.get('unit_price', 0),
                "tax_ids": tax_ids,
            }))

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': partner_id.id,
            'invoice_date': toc_document.get('date', fields.Date.today()),
            'journal_id': journal.id,
            'company_id': company.id,
            'currency_id': currency.id,
            'invoice_line_ids': invoice_lines,
            'toc_document_no': document_no,
            'toc_status': 'sent',
        }

        invoice = self.env['account.move'].create(invoice_vals)
        invoice.action_post()
        return invoice

    def _get_toc_document_by_id(self, toc_document_id):
        access_token = self.env['ir.config_parameter'].sudo().get_param('toc_online.access_token')
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
                _logger.error(f"Error when searching for documentTOC ID {toc_document_id}: {response.text}")
                return None
        except Exception as e:
            _logger.error(f"Error connecting to TOConline for documentID {toc_document_id}: {str(e)}")
            return None

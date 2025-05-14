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
        """Synchronization of invoices existing in TOCOnline and not in Odoo"""

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
                if doc.get("document_type") == "FT" and doc.get("id")
            ]

            existing_invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice')
            ])
            existing_toc_nos = set(
                existing_invoices.filtered(lambda inv: inv.toc_document_no).mapped('toc_document_no'))
            existing_toc_ids = set(
                existing_invoices.filtered(lambda inv: inv.toc_document_id).mapped('toc_document_id'))

            for doc in toc_ft_docs:
                document_no = doc.get("document_no")
                toc_id = str(doc.get("id"))

                if document_no:
                    if document_no in existing_toc_nos:
                        #_logger.info(f"Fatura já existe no Odoo com document_no: {document_no}")
                        continue
                else:
                    if toc_id in existing_toc_ids:
                        #_logger.info(f"Fatura sem document_no já existe no Odoo com toc_id: {toc_id}")
                        continue
                    else:
                        _logger.warning(f"Documento TOC com ID {toc_id} não tem 'document_no', mas será processado.")

                try:
                    self.create_invoice_in_odoo(doc)
                except Exception as e:
                    _logger.error("Erro ao criar fatura (ID TOC %s): %s", toc_id, str(e))

        except Exception as e:
            _logger.error("Erro durante a sincronização: %s", str(e), exc_info=True)
            raise UserError(f"Erro: {str(e)}")


        except Exception as e:
            _logger.error("Erro durante a sincronização: %s", str(e), exc_info=True)
            raise UserError(f"Erro: {str(e)}")

    def _map_toc_tax_to_odoo_tax(self, tax_code, tax_percentage, company):
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
        document_no = toc_document_data.get('document_no')

        existing_invoice = self.env['account.move'].search([
            ('toc_document_no', '=', document_no),
            ('move_type', '=', 'out_invoice')
        ], limit=1)

        if existing_invoice:
            _logger.warning(f"Fatura já existente no Odoo: {document_no} (ID {existing_invoice.id}) — não será criada novamente.")
            return existing_invoice

        toc_document_id = toc_document_data.get('id')
        toc_document = self._get_toc_document_by_id(toc_document_id)
        if not toc_document:
            raise UserError(f"Invoice {document_no} not found in TOConline.")

        toc_client_id = toc_document.get('customer_id')
        partner = self.env['res.partner'].search([('toc_online_id', '=', toc_client_id)], limit=1)

        if not partner:
            partner_name = toc_document.get('customer_name') or 'Cliente TOC'
            partner_vat = toc_document.get('customer_tax_id') or ''
            partner_email = toc_document.get('customer_email') or ''
            partner_phone = toc_document.get('customer_phone') or ''

            partner = self.env['res.partner'].create({
                'name': partner_name,
                'toc_online_id': toc_client_id,
                'vat': partner_vat,
                'email': partner_email,
                'phone': partner_phone,
                'customer_rank': 1,
            })
            _logger.info(f"Cliente criado no Odoo: {partner.name} (ID TOC: {toc_client_id})")

        company = self.env['res.company'].browse(2)
        _logger.info(f"Forçando empresa com ID = {company.id} e nome = {company.name}")
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

            invoice_lines.append((0, 0, {
                'product_id': product.id,
                'name': line.get('description', 'Produto TOC'),
                'quantity': line.get('quantity', 1),
                'price_unit': line.get('unit_price', 0),
                "tax_ids": tax_ids,
            }))

        status = toc_document.get('status', '')
        toc_invoice_status = ''
        toc_invoice_finalize = ''

        try:
            status_int = int(status)
        except (ValueError, TypeError):
            status_int = -1

        if status_int == 0:
            toc_invoice_status = 'sent'
            toc_invoice_finalize = 'draft'
        elif status_int == 1:
            toc_invoice_status = 'sent'
            toc_invoice_finalize = 'sent'
        elif status_int == 4:
            toc_invoice_status = 'sent'
            toc_invoice_finalize = 'cancelled'

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': toc_document.get('date', fields.Date.today()),
            'journal_id': journal.id,
            'company_id': company.id,
            'currency_id': currency.id,
            'invoice_line_ids': invoice_lines,
            'toc_document_no': document_no,
            'toc_status': toc_invoice_status,
            'toc_status_finalize': toc_invoice_finalize
        }

        invoice = self.env['account.move'].create(invoice_vals)
        invoice.action_post()
        _logger.info(f"Fatura criada no Odoo: {invoice.name} (TOC Nº {document_no})")
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
                _logger.error(f"Error when searching for document TOC ID {toc_document_id}: {response.text}")
                return None
        except Exception as e:
            _logger.error(f"Error connecting to TOConline for document ID {toc_document_id}: {str(e)}")
            return None

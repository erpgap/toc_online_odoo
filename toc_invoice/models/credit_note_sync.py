from odoo import models, api, fields
from datetime import datetime, date
from odoo.exceptions import UserError
import logging
from odoo.addons.toc_invoice.utils import TOC_BASE_URL
import requests

_logger = logging.getLogger(__name__)

class CreditNoteSync(models.Model):
    _name = 'credit.note.sync'
    _description = 'Sync Credit Notes from TOConline'

    @api.model
    def sync_credit_notes_from_toc(self):
        """Searches NCs from TOConline, shows those that do not exist in Odoo and creates them."""
        access_token = self.env['ir.config_parameter'].sudo().get_param('toc_online.access_token')
        if not access_token:
            raise UserError("TOConline access token not found.")

        url = f"{TOC_BASE_URL}/api/v1/commercial_sales_documents?filter[document_type]=NC&sort=-date"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        try:
            _logger.info("Request to TOConline:%s", url)
            response = requests.get(url, headers=headers, timeout=30)

            if response.status_code != 200:
                raise UserError(f"Error communicating with TOConline: {response.status_code} - {response.text}")

            documents = response.json()

            if not isinstance(documents, list):
                raise UserError("Unexpected TOConline response format.")


            toc_nc_docs = [
                doc for doc in documents
                if doc.get("document_type") == "NC"
                   and doc.get("document_no")
                   and doc.get("date")
            ]

            toc_doc_nos = [doc.get("document_no") for doc in toc_nc_docs]

            existing_credit_notes = self.env['account.move'].search([
                ('move_type', '=', 'out_refund'),
                ('toc_document_no_credit_note', 'in', toc_doc_nos)
            ])
            existing_toc_nos = set(existing_credit_notes.mapped('toc_document_no_credit_note'))

            new_toc_docs = [doc for doc in toc_nc_docs if doc.get("document_no") not in existing_toc_nos]

            for doc in new_toc_docs:
                self.create_credit_note_in_odoo(doc)

            _logger.info("Were found and inserted %d NC documents in Odoo", len(new_toc_docs))

        except Exception as e:
            _logger.error("Error during NC fetch: %s", str(e), exc_info=True)
            raise UserError(f"Erro: {str(e)}")

    def create_invoice_from_toc_document(self, toc_document_data, partner_id):
        document_no = toc_document_data.get('documentNo')
        if not document_no:
            raise UserError("Número do documento TOC não encontrado.")

        # Verifica se já existe uma fatura com esse número TOC
        existing_invoice = self.env['account.move'].search([
            ('toc_document_no', '=', document_no)
        ], limit=1)

        if existing_invoice:
            raise UserError(f"Já existe uma fatura com o número TOC {document_no}.")

        # Obter o ID da empresa enviado pelo TOConline
        toc_company_id = toc_document_data.get('company_id')
        if not toc_company_id:
            raise UserError("ID da empresa não foi fornecido no documento TOC.")

        # Mapear o ID do TOConline para o ID da empresa no Odoo
        company = self.env['res.company'].search([('toc_online_id', '=', toc_company_id)], limit=1)
        if not company:
            raise UserError(f"Empresa com TOConline ID {toc_company_id} não encontrada no Odoo.")

        # Buscar um produto da empresa
        product = self.env['product.product'].with_company(company).search([], limit=1)
        if not product:
            raise UserError("Nenhum produto encontrado para criar a linha da fatura.")

        # Filtrar os impostos da empresa correta
        taxes = product.taxes_id.filtered(lambda t: t.company_id == company)

        # Buscar o diário de vendas da empresa correta
        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('company_id', '=', company.id)
        ], limit=1)

        if not journal:
            raise UserError("Nenhum diário de vendas encontrado para a empresa selecionada.")

        # Criar os valores da fatura
        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': partner_id.id,
            'invoice_date': fields.Date.today(),
            'journal_id': journal.id,
            'company_id': company.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': product.id,
                'name': f"Fatura TOC {document_no}",
                'quantity': 1.0,
                'price_unit': toc_document_data.get('total', 0),
                'tax_ids': [(6, 0, taxes.ids)],
            })],
            'toc_document_no': document_no,
        }

        # Criar e validar a fatura no contexto da empresa correta
        invoice = self.env['account.move'].with_company(company).create(invoice_vals)
        invoice.action_post()

        return invoice

    def _get_toc_document_by_id(self, toc_document_id):
        """Retrieves TOConline credit document based on ID"""
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
                _logger.error(f"Error fetching TOConline document ID {toc_document_id}: {response.text}")
                return None
        except Exception as e:
            _logger.error(f"Error connecting to TOConline to fetch document ID{toc_document_id}: {str(e)}")
            return None

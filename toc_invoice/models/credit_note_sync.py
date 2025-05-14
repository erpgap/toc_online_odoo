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

    def create_credit_note_in_odoo(self, toc_document_data):
        """Creates the credit note in Odoo based on the complete data from TOConline"""
        toc_document_id = toc_document_data.get('id')
        document_no = toc_document_data.get('document_no')

        toc_document = self._get_toc_document_by_id(toc_document_id)

        if not toc_document:
            raise UserError(f"Credit document{document_no} not found in TOConline.")

        if isinstance(toc_document, dict):
            toc_client_id = toc_document.get('customer_id')
        else:
            raise UserError(f"Unexpected format for toc_document: {type(toc_document)}")

        partner_id = self.env['res.partner'].search([('toc_online_id', '=', toc_client_id)], limit=1)
        if not partner_id:
            raise UserError(f"Customer with TOConline ID{toc_client_id} not found in Odoo.")

        parent_doc_no = toc_document.get('parent_document_reference')
        if not parent_doc_no:
            raise UserError(f"credit note {document_no} has no reference to the original invoice.")

        invoice_id = self.env['account.move'].search([('toc_document_no', '=', parent_doc_no)], limit=1)
        if not invoice_id:
            raise UserError(f"Original invoice with TOC no.{parent_doc_no}not found.")

        company_id = invoice_id.company_id

        print("este é o id da minha empresa" , company_id)

        valid_taxes = invoice_id.invoice_line_ids[0].tax_ids.filtered(
            lambda t: not (t.amount == 0 and t.company_id != company_id)
        )

        print("estas são as minhas taxas " , valid_taxes)
        credit_note_vals = {
            'move_type': 'out_refund',
            'partner_id': partner_id.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {
                'product_id': invoice_id.invoice_line_ids[0].product_id.id,
                'name': f"Nota de Crédito para fatura {parent_doc_no}",
                'quantity': 1.0,
                'price_unit': invoice_id.invoice_line_ids[0].price_unit,
                'tax_ids': [(6, 0, valid_taxes.ids)],
            })],
            'toc_document_no_credit_note': document_no,
            'company_id': company_id.id,
            'toc_status': 'sent',
            'toc_status_credit_note' : 'sent'

        }

        credit_note = self.env['account.move'].create(credit_note_vals)

        if not credit_note:
            raise UserError("Error creating credit note in Odoo.")

        _logger.info(f"credit note {document_no} successfully created in Odoo.")
        return credit_note

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
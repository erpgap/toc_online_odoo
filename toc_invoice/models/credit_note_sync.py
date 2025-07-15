import logging
from datetime import datetime, date
import requests

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from odoo.addons.toc_invoice.utils import TOC_BASE_URL

_logger = logging.getLogger(__name__)



class CreditNoteSync(models.Model):
    _name = 'credit.note.sync'
    _description = 'Sync Credit Notes from TOConline'

    def create_credit_note_in_odoo(self, toc_document_data):
        """Create a credit note in Odoo from a single TOConline document."""

        toc_document_id = toc_document_data.get('id')
        document_no = toc_document_data.get('document_no')

        toc_company_id = toc_document_data.get('company_id')
        company = self.env['res.company'].search([('toc_company_id', '=', toc_company_id)], limit=1)
        if not company:
            raise UserError(f"Company with TOConline ID {toc_company_id} not found in Odoo.")

        toc_document = self._get_toc_document_by_id(toc_document_id, company)
        if not toc_document:
            raise UserError(f"Credit note {document_no} not found in TOConline.")

        if not isinstance(toc_document, dict):
            raise UserError(f"Unexpected format for TOConline document: {type(toc_document)}")

        toc_client_id = toc_document.get('customer_id')
        partner = self.env['res.partner'].search([('toc_online_id', '=', toc_client_id)], limit=1)
        if not partner:
            raise UserError(f"Customer with TOConline ID {toc_client_id} not found in Odoo.")

        parent_doc_no = toc_document.get('parent_document_reference')
        if not parent_doc_no:
            raise UserError(f"Credit note {document_no} has no reference to the original invoice.")

        invoice = self.env['account.move'].search([('toc_document_no', '=', parent_doc_no)], limit=1)

        if not invoice:
            raise UserError(f"Original invoice with TOConline number {parent_doc_no} not found in Odoo.")

        self = self.with_company(company).sudo()

        valid_taxes = invoice.invoice_line_ids[0].tax_ids.filtered(
            lambda t: not (t.amount == 0 and t.company_id != company)
        )

        reverse_moves = invoice._reverse_moves(default_values_list=[{
            'ref': f"Credit Note imported from TOConline ({document_no})",
            'date': fields.Date.today(),
        }], cancel=False)

        credit_note = reverse_moves and reverse_moves[0]

        if not credit_note:
            raise UserError(f"Failed to create credit note from invoice {invoice.name}")

        line_data = toc_document_data.get('lines', [{}])[0]

        credit_note_line = credit_note.invoice_line_ids[0]
        credit_note_line.write({
            'name': toc_document_data.get('description') or credit_note_line.name,
            'price_unit': line_data.get('unit_price', credit_note_line.price_unit),
            'quantity': line_data.get('quantity', 1.0),
        })

        credit_note.write({
            'toc_document_no_credit_note': document_no,
            'toc_status': 'sent',
            'toc_status_credit_note': 'sent'
        })

        credit_note.action_post()

        _logger.info(f"Credit note {document_no} successfully created in Odoo.")
        return credit_note

    def _get_toc_document_by_id(self, toc_document_id, company):
        """Retrieve a single TOConline document by ID for a specific company"""

        access_token = self.env['toc.api'].get_access_token(company=company)
        if not access_token:
            raise UserError(f"TOConline access token not found for company {company.name}.")

        url = f"{TOC_BASE_URL}/api/v1/commercial_sales_documents/{toc_document_id}"

        try:
            response = self.env['toc.api'].toc_request(
                method='GET',
                url=url,
                access_token=access_token,
            )
            return response.json()
        except Exception as e:
            _logger.error(f"Error fetching TOConline document ID {toc_document_id}: {str(e)}")
            return None

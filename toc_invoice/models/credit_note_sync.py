import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .toc_online_service import TocOnlineService

_logger = logging.getLogger(__name__)


class CreditNoteSync(models.AbstractModel):
    _name = 'credit.note.sync'
    _description = 'Sync Credit Notes from TOConline'

    def create_credit_note_in_odoo(self, toc_document_data):
        """Create a credit note in Odoo from a single TOConline document."""

        toc_document_id = toc_document_data.get('id')
        document_no = toc_document_data.get('document_no')

        toc_company_id = toc_document_data.get('company_id')
        company = self.env['res.company'].search([('toc_company_id', '=', toc_company_id)], limit=1)
        if not company:
            raise UserError(_("Company with TOConline ID %s not found in Odoo.") % toc_company_id)

        service = TocOnlineService(company, self.env)
        toc_document = service.get_document_by_id(toc_document_id)
        if not toc_document:
            raise UserError(_("Credit note %s not found in TOConline.") % document_no)

        if not isinstance(toc_document, dict):
            raise UserError(_("Unexpected format for TOConline document: %s") % type(toc_document))

        toc_client_id = toc_document.get('customer_id')
        partner = self.env['res.partner'].with_company(company).search(
            [('toc_online_id', '=', toc_client_id)], limit=1,
        )
        if not partner:
            raise UserError(_("Customer with TOConline ID %s not found in Odoo.") % toc_client_id)

        parent_doc_no = toc_document.get('parent_document_reference')
        if not parent_doc_no:
            raise UserError(_("Credit note %s has no reference to the original invoice.") % document_no)

        invoice = self.env['account.move'].search([('toc_document_no', '=', parent_doc_no)], limit=1)

        if not invoice:
            raise UserError(
                _("Original invoice with TOConline number %s not found in Odoo.") % parent_doc_no
            )

        self = self.with_company(company).sudo()

        invoice_product_lines = invoice.invoice_line_ids.filtered(lambda l: not l.display_type)
        valid_taxes = invoice_product_lines[0].tax_ids.filtered(
            lambda t: not (t.amount == 0 and t.company_id != company)
        ) if invoice_product_lines else self.env['account.tax']

        reverse_moves = invoice._reverse_moves(default_values_list=[{
            'ref': f"Credit Note imported from TOConline ({document_no})",
            'date': fields.Date.today(),
        }], cancel=False)

        credit_note = reverse_moves and reverse_moves[0]

        if not credit_note:
            raise UserError(_("Failed to create credit note from invoice %s") % invoice.name)

        line_data = toc_document_data.get('lines', [{}])[0]

        cn_product_lines = credit_note.invoice_line_ids.filtered(lambda l: not l.display_type)
        credit_note_line = cn_product_lines[0] if cn_product_lines else credit_note.invoice_line_ids[0]
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

        _logger.info("Credit note %s successfully created in Odoo.", document_no)
        return credit_note

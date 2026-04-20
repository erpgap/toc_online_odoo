from markupsafe import Markup

from odoo import _, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

from ..models.toc_online_service import TocOnlineService


class TocLinkInvoiceWizard(models.TransientModel):
    _name = 'toc.link.invoice.wizard'
    _description = 'Link existing TOConline invoice to Odoo'

    invoice_id = fields.Many2one('account.move', required=True, readonly=True)
    toc_document_no = fields.Char(string="TOConline Document Number", required=True)

    def action_confirm_link(self):
        self.ensure_one()
        invoice = self.invoice_id

        if invoice.state != 'posted':
            raise UserError(_("The invoice must be posted before linking it to TOConline."))
        if invoice.move_type not in ('out_invoice', 'out_refund'):
            raise UserError(_("Only customer invoices and credit notes can be linked."))
        if not invoice.company_id.toc_online_enabled:
            raise UserError(_("TOConline is not enabled for company %s.") % invoice.company_id.display_name)
        if not invoice.journal_id.send_to_toconline:
            raise UserError(_("The journal %s is not configured to send documents to TOConline.") % invoice.journal_id.display_name)
        if invoice.move_type == 'out_invoice' and invoice.toc_status != 'draft':
            raise UserError(_("This invoice is already linked to TOConline."))
        if invoice.move_type == 'out_refund' and invoice.toc_status_credit_note != 'draft':
            raise UserError(_("This credit note is already linked to TOConline."))

        document_no = (self.toc_document_no or '').strip()
        if not document_no:
            raise UserError(_("Please enter a TOConline document number."))

        is_credit_note = invoice.move_type == 'out_refund'
        duplicate_field = 'toc_document_no_credit_note' if is_credit_note else 'toc_document_no'
        duplicate_domain = [
            ('id', '!=', invoice.id),
            ('company_id', '=', invoice.company_id.id),
            (duplicate_field, '=', document_no),
        ]
        existing = self.env['account.move'].search(duplicate_domain, limit=1)
        if existing:
            raise ValidationError(_(
                "TOConline document %(doc_no)s is already linked to %(move)s."
            ) % {'doc_no': document_no, 'move': existing.display_name})

        service = TocOnlineService(invoice.company_id, self.env)
        doc = service.get_document_fields_by_number(document_no)

        toc_total = float(doc.get('gross_total') or 0.0)
        rounding = invoice.currency_id.rounding or 0.01
        if float_compare(toc_total, invoice.amount_total, precision_rounding=rounding) != 0:
            raise UserError(_(
                "Total mismatch between Odoo and TOConline for document %(doc_no)s.\n"
                "Odoo total: %(odoo_total)s\n"
                "TOConline total: %(toc_total)s\n"
                "Please verify the document number."
            ) % {
                'doc_no': document_no,
                'odoo_total': invoice.amount_total,
                'toc_total': toc_total,
            })

        public_link = doc.get('public_link') or ''
        if is_credit_note:
            vals = {
                'toc_document_no_credit_note': document_no,
                'toc_invoice_url': public_link,
                'toc_status_credit_note': 'sent',
            }
        else:
            vals = {
                'toc_document_no': document_no,
                'toc_document_id': str(doc.get('id') or ''),
                'toc_invoice_url': public_link,
                'toc_status': 'sent',
            }
        invoice.write(vals)

        if public_link:
            msg = _(
                "Linked to existing TOConline document <b>%(doc_no)s</b>.<br/>"
                "Public link: <a href='%(link)s' target='_blank'>%(link)s</a>"
            ) % {'doc_no': document_no, 'link': public_link}
        else:
            msg = _("Linked to existing TOConline document <b>%s</b>.") % document_no
        invoice.message_post(body=Markup(msg))

        return {'type': 'ir.actions.act_window_close'}

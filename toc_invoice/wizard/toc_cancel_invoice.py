from odoo import models, fields, api
from odoo.exceptions import UserError

class CancelInvoiceWizard(models.TransientModel):
    _name = 'cancel.invoice.wizard'
    _description = 'Wizard to cancel invoice in TOConline'

    cancel_reason = fields.Text(string="Reason for Cancellation", required=True)

    def confirm_cancel_invoice(self):
        active_id = self.env.context.get('active_id')
        invoice = self.env['account.move'].browse(active_id)
        invoice.with_context(cancel_reason=self.cancel_reason).action_cancel_invoice_toconline()
        return {'type': 'ir.actions.act_window_close'}

from odoo import models, fields


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    send_to_toconline = fields.Boolean(
        string="Send to TOConline",
        default=False,
        help="If unchecked, this journal's invoices will not be automatically sent to TOConline upon confirmation."
    )

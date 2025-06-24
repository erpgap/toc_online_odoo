from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    toc_company_id = fields.Char(string="Company ID", help="Company ID on TOConline platform")
    toc_cash_account_id = fields.Char(string="Cash Account ID")
    toc_online_client_id = fields.Char(string="Client ID")
    toc_online_client_secret = fields.Char(string="Client Secret")

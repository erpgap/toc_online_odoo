from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    toc_company_id = fields.Char(string="Company ID in TOConline")

    toc_cash_account_id = fields.Char(string="TOConline Cash Account ID")
    toc_online_client_id = fields.Char(string="TOConline Client ID")
    toc_online_client_secret = fields.Char(string="TOConline Client Secret")

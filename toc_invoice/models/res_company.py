from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    toc_online_enabled = fields.Boolean(string="Send to TOC Online", default=False)
    toc_company_id = fields.Char(string="Company ID", help="Company ID on TOConline platform")
    toc_cash_account_id = fields.Char(string="Cash Account ID")
    toc_online_client_id = fields.Char(string="Client ID")
    toc_online_client_secret = fields.Char(string="Client Secret")
    toc_auth_url = fields.Char(
        string="OAuth Authentication URL",
    )
    toc_api_url = fields.Char(
        string="API Base URL",
    )
    toc_redirect_uri = fields.Char(
        string="Redirect URI",
    )
    toc_online_access_token = fields.Char(string="Access Token", copy=False, groups="base.group_system")
    toc_online_refresh_token = fields.Char(string="Refresh Token", copy=False, groups="base.group_system")
    toc_online_token_expiry = fields.Datetime(string="Token Expiry", copy=False, groups="base.group_system")

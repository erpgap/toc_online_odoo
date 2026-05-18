from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    toc_company_id = fields.Char(string="Company ID", help="Company ID on TOConline platform")
    toc_cash_account_id = fields.Char(string="Cash Account ID")
    toc_online_client_id = fields.Char(string="Client ID")
    toc_online_client_secret = fields.Char(string="Client Secret")
    toc_api_url = fields.Char(string="API Base URL")
    toc_auth_url = fields.Char(string="OAuth Authentication URL")
    toc_redirect_uri = fields.Char(string="Redirect URI")

    def _get_toc_api_url(self):
        self.ensure_one()
        return (self.toc_api_url or '').rstrip('/')

    def _get_toc_auth_url(self):
        self.ensure_one()
        return (self.toc_auth_url or '').rstrip('/')

    def _get_toc_redirect_uri(self):
        self.ensure_one()
        return (self.toc_redirect_uri or '').rstrip('/')

    def _get_toc_token_url(self):
        return f"{self._get_toc_auth_url()}/token"

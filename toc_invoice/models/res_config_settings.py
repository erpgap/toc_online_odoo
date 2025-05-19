from odoo import models, fields, _
import requests
from datetime import timedelta
from odoo.addons.toc_invoice.utils import token_url

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    toc_online_client_id = fields.Char(
        string="TOConline Client ID",
        related='company_id.toc_online_client_id',
        readonly=False
    )
    toc_online_client_secret = fields.Char(
        string="TOConline Client Secret",
        related='company_id.toc_online_client_secret',
        readonly=False
    )

    def exchange_authorization_code_and_save_tokens(self):
        """Exchange the authorization code for tokens and save them in the system."""
        company = self.env.company

        client_id = company.toc_online_client_id
        client_secret = company.toc_online_client_secret
        authorization_code = self.env['ir.config_parameter'].sudo().get_param('toc_online.authorization_code')
        redirect_uri = self.env['ir.config_parameter'].sudo().get_param('web.base.url')

        if not authorization_code:
            raise ValueError(_("Missing Authorization Code."))

        url = token_url
        data = {
            'grant_type': 'authorization_code',
            'code': authorization_code,
            'redirect_uri': redirect_uri,
            'client_id': client_id,
            'client_secret': client_secret,
        }

        response = requests.post(url, data=data)
        if response.status_code != 200:
            raise ValueError(_(f"Error exchanging authorization code: {response.text}"))

        tokens = response.json()

        company.toc_online_access_token = tokens.get('access_token', '')
        company.toc_online_refresh_token = tokens.get('refresh_token', '')
        company.toc_online_token_expiry = fields.Datetime.now() + timedelta(seconds=tokens.get('expires_in', 3600))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'TOConline',
                'message': 'Tokens successfully obtained and saved!',
                'sticky': False,
            }
        }

from odoo import models, fields, api, _
import requests
from datetime import timedelta
from odoo.addons.toc_invoice.utils import token_url


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    toc_online_client_id = fields.Char(
        string="Client ID",
        related='company_id.toc_online_client_id',
        readonly=False
    )
    toc_online_client_secret = fields.Char(
        string="Client Secret",
        related='company_id.toc_online_client_secret',
        readonly=False
    )
    toc_company_id = fields.Char(
        string="Company ID",
        related='company_id.toc_company_id',
        readonly=True
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        company = self.env.company
        res.update({
            'toc_online_client_id': company.toc_online_client_id,
            'toc_online_client_secret': company.toc_online_client_secret,
        })
        return res

    def set_values(self):
        super().set_values()
        company = self.env.company
        company.write({
            'toc_online_client_id': self.toc_online_client_id,
            'toc_online_client_secret': self.toc_online_client_secret,
        })


    @api.onchange('toc_online_client_id', 'toc_online_client_secret')
    def _onchange_clear_tokens_if_missing_credentials(self):
        if not self.toc_online_client_id or not self.toc_online_client_secret:
            config = self.env['ir.config_parameter'].sudo()
            config.set_param('toc_online.access_token', '')
            config.set_param('toc_online.refresh_token', '')
            config.set_param('toc_online.token_expiry', '')

    def exchange_authorization_code_and_save_tokens(self):
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

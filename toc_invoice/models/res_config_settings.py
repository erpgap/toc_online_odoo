from odoo import models, fields
import requests
from datetime import timedelta


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    toc_online_client_id = fields.Char(
        string="TOConline Client ID",
        config_parameter='toc_online.client_id'
    )
    toc_online_client_secret = fields.Char(
        string="TOConline Client Secret",
        config_parameter='toc_online.client_secret'
    )
    toc_online_access_token = fields.Char(
        string="TOConline Access Token",
        config_parameter='toc_online.access_token'
    )
    toc_online_refresh_token = fields.Char(
        string="TOConline Refresh Token",
        config_parameter='toc_online.refresh_token'
    )
    toc_online_authorization_code = fields.Char(
        string="TOConline Authorization Code",
        config_parameter='toc_online.authorization_code'
    )
    toc_online_token_expiry = fields.Datetime(
        string="TOConline Token Expiry Date",
        config_parameter='toc_online.token_expiry'
    )

    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        params = self.env['ir.config_parameter'].sudo()

        res.update({
            'toc_online_client_id': params.get_param('toc_online.client_id', default=''),
            'toc_online_client_secret': params.get_param('toc_online.client_secret', default=''),
            'toc_online_access_token': params.get_param('toc_online.access_token', default=''),
            'toc_online_refresh_token': params.get_param('toc_online.refresh_token', default=''),
            'toc_online_authorization_code': params.get_param('toc_online.authorization_code', default=''),
            'toc_online_token_expiry': params.get_param('toc_online.token_expiry', default=''),

        })
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        params = self.env['ir.config_parameter'].sudo()

        params.set_param('toc_online.client_id', self.toc_online_client_id)
        params.set_param('toc_online.client_secret', self.toc_online_client_secret)
        params.set_param('toc_online.access_token', self.toc_online_access_token)
        params.set_param('toc_online.refresh_token', self.toc_online_refresh_token)
        params.set_param('toc_online.authorization_code', self.toc_online_authorization_code)
        params.set_param('toc_online.token_expiry', self.toc_online_token_expiry)

    def exchange_authorization_code_and_save_tokens(self):
        """Troca o authorization code por tokens e guarda-os no sistema."""
        params = self.env['ir.config_parameter'].sudo()

        client_id = params.get_param('toc_online.client_id')
        client_secret = params.get_param('toc_online.client_secret')
        authorization_code = params.get_param('toc_online.authorization_code')
        redirect_uri = "https://TUA_URL_DO_ODDO.com"  # Muda isto conforme teu setup

        if not authorization_code:
            raise ValueError("Authorization Code em falta. Por favor, preencha-o nas configurações.")

        url = "https://api.toctoc.com/oauth/token"
        data = {
            'grant_type': 'authorization_code',
            'code': authorization_code,
            'redirect_uri': redirect_uri,
            'client_id': client_id,
            'client_secret': client_secret,
        }

        response = requests.post(url, data=data)
        if response.status_code != 200:
            raise ValueError(f"Erro ao trocar authorization code: {response.text}")

        tokens = response.json()

        params.set_param('toc_online.access_token', tokens.get('access_token', ''))
        params.set_param('toc_online.refresh_token', tokens.get('refresh_token', ''))

        expiry = fields.Datetime.now() + timedelta(seconds=tokens.get('expires_in', 3600))
        params.set_param('toc_online.token_expiry', expiry)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'TOConline',
                'message': 'Tokens obtidos e guardados com sucesso!',
                'sticky': False,
            }
        }

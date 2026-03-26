from odoo import models, fields, api, _

from .toc_online_service import TocOnlineService


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    toc_online_enabled = fields.Boolean(
        related='company_id.toc_online_enabled',
        readonly=False,
    )
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
    toc_auth_url = fields.Char(
        string="OAuth Authentication URL",
        related='company_id.toc_auth_url',
        readonly=False,
    )
    toc_api_url = fields.Char(
        string="API Base URL",
        related='company_id.toc_api_url',
        readonly=False,
    )
    toc_redirect_uri = fields.Char(
        string="Redirect URI",
        related='company_id.toc_redirect_uri',
        readonly=False,
    )


    def set_values(self):
        super().set_values()
        company = self.env.company
        if not self.toc_online_client_id or not self.toc_online_client_secret or not self.toc_online_enabled:
            company.write({
                'toc_online_access_token': False,
                'toc_online_refresh_token': False,
                'toc_online_token_expiry': False,
            })

    def exchange_authorization_code_and_save_tokens(self):
        company = self.env.company
        service = TocOnlineService(company, self.env)
        service._check_configuration()

        authorization_code = self.env['ir.config_parameter'].sudo().get_param('toc_online.authorization_code')
        if not authorization_code:
            raise ValueError(_("Missing Authorization Code."))

        service._get_tokens(authorization_code)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'TOConline',
                'message': _('Tokens successfully obtained and saved!'),
                'sticky': False,
            }
        }

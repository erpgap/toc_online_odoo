from odoo import http
from odoo.http import request

class TOConlineOAuth(http.Controller):

    @http.route('/oauth/callback', type='http', auth='public', csrf=False)
    def toc_oauth_callback(self, **kwargs):
        authorization_code = kwargs.get('code')

        if not authorization_code:
            return "Erro: Código de autorização não recebido."

        # Armazena o código nos parâmetros do sistema
        request.env['ir.config_parameter'].sudo().set_param('toc_online.authorization_code', authorization_code)

        return "Autorização concluída. Agora pode enviar faturas para TOConline."

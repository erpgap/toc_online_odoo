from odoo import http
from odoo.http import request

class TocOauthController(http.Controller):

    @http.route('/oauth/callback', type='http', auth='public', csrf=False)
    def oauth_callback(self, **kwargs):
        code = kwargs.get('code')
        error = kwargs.get('error')

        if error:
            return f"Erro recebido da TOConline: {error}"

        if not code:
            return "Erro: Código de autorização não recebido."

        # Troca o code pelo token
        toc_api = request.env['toc.api'].sudo()
        tokens = toc_api._get_tokens(code)

        return "Autenticação bem-sucedida com TOConline. Pode fechar esta janela."

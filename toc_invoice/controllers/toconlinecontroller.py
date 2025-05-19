from odoo import http, _
from odoo.http import request


class TocOauthController(http.Controller):

    @http.route('/oauth/callback', type='http', auth='public', csrf=False)
    def oauth_callback(self, **kwargs):
        code = kwargs.get('code')
        error = kwargs.get('error')

        if error:
            return f"Error received from TOConline: {error}"

        if not code:
            return "Error: Authorization code not received."

        toc_api = request.env['toc.api'].sudo()
        tokens = toc_api._get_tokens(code)

        return "Successful authentication with TOConline. You can close this window."

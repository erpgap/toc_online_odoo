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

    @http.route('/toc/test_create_customer', type='json', auth='user', csrf=False)
    def test_create_customer(self, **kwargs):
        partner_id = kwargs.get('partner_id')
        access_token = kwargs.get('access_token')

        if not partner_id or not access_token:
            return {'error': 'Missing partner_id or access_token'}

        partner = request.env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {'error': 'Partner not found'}

        try:
            move = request.env['account.move'].sudo().search([], limit=1)  # ou um específico
            toc_id = move.get_or_create_customer_in_toconline(access_token, partner)
            return {'success': True, 'toc_id': toc_id}
        except Exception as e:
            return {'error': str(e)}

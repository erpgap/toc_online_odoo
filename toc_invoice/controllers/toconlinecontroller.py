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

        company = request.env.company.sudo()
        request.env['toc.api'].sudo()._get_tokens(code, company=company)

        return "Successful authentication with TOConline. You can close this window."

    @http.route('/toc/test_create_customer', type='jsonrpc', auth='user', csrf=False)
    def test_create_customer(self, **kwargs):
        partner_id = kwargs.get('partner_id')

        if not partner_id:
            return {'error': 'Missing partner_id'}

        partner = request.env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {'error': 'Partner not found'}

        try:
            company = partner.company_id or request.env.company
            access_token = request.env['toc.api'].sudo().get_access_token(company=company)
            move = request.env['account.move'].sudo().search([], limit=1)
            toc_id = move.get_or_create_customer_in_toconline(access_token, partner, company=company)
            return {'success': True, 'toc_id': toc_id}
        except Exception as e:
            return {'error': str(e)}

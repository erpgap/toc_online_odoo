from odoo import http, _
from odoo.http import request

from ..models.toc_online_service import TocOnlineService


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
        service = TocOnlineService(company, request.env)
        service._get_tokens(code)

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
            service = TocOnlineService(company, request.env)
            toc_id = service.get_or_create_customer(partner)
            return {'success': True, 'toc_id': toc_id}
        except Exception as e:
            return {'error': str(e)}

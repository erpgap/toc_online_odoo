import unittest
import logging
from odoo.tests.common import TransactionCase
from unittest.mock import patch, MagicMock
from odoo.exceptions import UserError

from ..models.toc_online_service import TocOnlineService

_logger = logging.getLogger(__name__)

class TestTOCIntegration(TransactionCase):

    def setUp(self):
        super().setUp()

        self.env.company.sudo().write({
            'toc_online_enabled': True,
            'toc_online_client_id': 'pt999999990_c12610-927f0c2762239267',
            'toc_online_client_secret': 'ec8a0ca36e2e539a483baf5b87358ade',
            'toc_api_url': 'https://test.toconline.com',
            'toc_auth_url': 'https://test.toconline.com/oauth',
            'toc_redirect_uri': 'https://test.example.com/oauth/callback',
            'toc_online_access_token': 'dummy_token',
            'toc_online_token_expiry': '2099-01-01 00:00:00',
        })

        self.partner = self.env['res.partner'].create({
            'name': 'sera',
            'email': 'serao@example.com',
            'vat': '/',
            'street': 'Test Street',
            'city': 'Lisboa',
            'zip': '1000-001',
            'country_id': self.env.ref('base.pt').id,
            'toc_online_id': False
        })

        self.product = self.env['product.product'].create({
            'default_code': 'COD_XX2',
            'name': 'ProductT',
            'list_price': 100.0,
        })

        self.move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': '2024-01-01',
            'invoice_date_due': '2024-01-10',
            'currency_id': self.env.ref('base.EUR').id,
            'journal_id': self.env['account.journal'].search([('type', '=', 'sale')], limit=1).id,
        })


    @patch('odoo.addons.toc_invoice.models.toc_online_service.requests.request')
    def test_create_customer_when_not_exists(self, mock_request):
        # First call: search by email returns empty
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.text = '{"data": []}'
        search_response.json.return_value = {'data': []}

        # Second call: create customer
        create_response = MagicMock()
        create_response.status_code = 201
        create_response.text = '{"data": {"id": "toc_customer_created_001"}}'
        create_response.json.return_value = {'data': {'id': 'toc_customer_created_001'}}

        mock_request.side_effect = [search_response, create_response]

        service = TocOnlineService(self.env.company, self.env)
        service._access_token = 'dummy_token'
        toc_id = service.get_or_create_customer(self.partner)

        self.assertEqual(toc_id, 'toc_customer_created_001')
        self.assertEqual(self.partner.toc_online_id, 'toc_customer_created_001')

    @patch('odoo.addons.toc_invoice.models.toc_online_service.requests.request')
    def test_existing_customer_found_by_email(self, mock_request):
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.text = '{"data": [{"id": "toc_customer_found_002"}]}'
        search_response.json.return_value = {'data': [{'id': 'toc_customer_found_002'}]}

        mock_request.return_value = search_response

        service = TocOnlineService(self.env.company, self.env)
        service._access_token = 'dummy_token'
        toc_id = service.get_or_create_customer(self.partner)

        self.assertEqual(toc_id, 'toc_customer_found_002')
        self.assertEqual(self.partner.toc_online_id, 'toc_customer_found_002')

    @patch('odoo.addons.toc_invoice.models.toc_online_service.requests.request')
    def test_customer_creation_fails(self, mock_request):
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.text = '{"data": []}'
        search_response.json.return_value = {'data': []}

        create_response = MagicMock()
        create_response.status_code = 400
        create_response.text = "Invalid data"
        create_response.reason = "Bad Request"

        mock_request.side_effect = [search_response, create_response]

        service = TocOnlineService(self.env.company, self.env)
        service._access_token = 'dummy_token'
        with self.assertRaises(UserError):
            service.get_or_create_customer(self.partner)

    @patch('odoo.addons.toc_invoice.models.toc_online_service.requests.request')
    def test_create_product_when_not_exists(self, mock_request):
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.text = '{"data": []}'
        search_response.json.return_value = {'data': []}

        create_response = MagicMock()
        create_response.status_code = 201
        create_response.text = '{"data": {"id": "toc_product_created_001"}}'
        create_response.json.return_value = {'data': {'id': 'toc_product_created_001'}}

        mock_request.side_effect = [search_response, create_response]

        service = TocOnlineService(self.env.company, self.env)
        service._access_token = 'dummy_token'
        product_id = service.get_or_create_product(self.product)

        self.assertEqual(product_id, 'toc_product_created_001')

    @patch('odoo.addons.toc_invoice.models.toc_online_service.requests.request')
    def test_product_already_exists(self, mock_request):
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.text = '{"data": [{"id": "toc_product_found_002"}]}'
        search_response.json.return_value = {'data': [{'id': 'toc_product_found_002'}]}

        mock_request.return_value = search_response

        service = TocOnlineService(self.env.company, self.env)
        service._access_token = 'dummy_token'
        product_id = service.get_or_create_product(self.product)

        self.assertEqual(product_id, 'toc_product_found_002')

    @patch('odoo.addons.toc_invoice.models.toc_online_service.requests.request')
    def test_product_creation_fails(self, mock_request):
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.text = '{"data": []}'
        search_response.json.return_value = {'data': []}

        create_response = MagicMock()
        create_response.status_code = 400
        create_response.text = "Invalid product data"
        create_response.reason = "Bad Request"

        mock_request.side_effect = [search_response, create_response]

        service = TocOnlineService(self.env.company, self.env)
        service._access_token = 'dummy_token'
        with self.assertRaises(UserError):
            service.get_or_create_product(self.product)

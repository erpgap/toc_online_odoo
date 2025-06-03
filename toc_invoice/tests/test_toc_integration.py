import unittest
import logging
from odoo.tests.common import TransactionCase
from unittest.mock import patch
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class TestTOCIntegration(TransactionCase):

    def setUp(self):
        super().setUp()

        # Configuração real do cliente TOC (não usar em produção!)
        self.env.company.sudo().write({
            'toc_online_client_id': 'pt999999990_c12610-927f0c2762239267',
            'toc_online_client_secret': 'ec8a0ca36e2e539a483baf5b87358ade',
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


    @patch('requests.get')
    @patch('requests.post')
    def test_create_customer_when_not_exists(self, mock_post, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'data': []}

        mock_post.return_value.status_code = 201
        mock_post.return_value.json.return_value = {
            'data': {'id': 'toc_customer_created_001'}
        }

        access_token = 'dummy_token'
        toc_id = self.move.get_or_create_customer_in_toconline(access_token, self.partner)

        self.assertEqual(toc_id, 'toc_customer_created_001')
        self.assertEqual(self.partner.toc_online_id, 'toc_customer_created_001')

    @patch('requests.get')
    def test_existing_customer_found_by_email(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'data': [{'id': 'toc_customer_found_002'}]
        }

        access_token = 'dummy_token'
        toc_id = self.move.get_or_create_customer_in_toconline(access_token, self.partner)

        self.assertEqual(toc_id, 'toc_customer_found_002')
        self.assertEqual(self.partner.toc_online_id, 'toc_customer_found_002')

    @patch('requests.get')
    @patch('requests.post')
    def test_customer_creation_fails(self, mock_post, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'data': []}

        mock_post.return_value.status_code = 400
        mock_post.return_value.text = "Invalid data"

        access_token = 'dummy_token'
        with self.assertRaises(UserError) as cm:
            self.move.get_or_create_customer_in_toconline(access_token, self.partner)

        self.assertIn("Erro ao criar cliente", str(cm.exception))

    @patch('requests.get')
    @patch('requests.post')
    def test_create_product_when_not_exists(self, mock_post, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'data': []}

        mock_post.return_value.status_code = 201
        mock_post.return_value.json.return_value = {
            'data': {'id': 'toc_product_created_001'}
        }

        access_token = 'dummy_token'
        product_id = self.move.get_or_create_product_in_toconline(access_token, self.product)

        self.assertEqual(product_id, 'toc_product_created_001')

    @patch('requests.get')
    def test_product_already_exists(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'data': [{'id': 'toc_product_found_002'}]
        }

        access_token = 'dummy_token'
        product_id = self.move.get_or_create_product_in_toconline(access_token, self.product)

        self.assertEqual(product_id, 'toc_product_found_002')

    @patch('requests.get')
    @patch('requests.post')
    def test_product_creation_fails(self, mock_post, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'data': []}

        mock_post.return_value.status_code = 400
        mock_post.return_value.text = "Invalid product data"

        access_token = 'dummy_token'
        with self.assertRaises(UserError) as cm:
            self.move.get_or_create_product_in_toconline(access_token, self.product)

        self.assertIn("Error creating product", str(cm.exception))

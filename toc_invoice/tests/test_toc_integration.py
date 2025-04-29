from odoo.tests.common import TransactionCase
from unittest.mock import patch
import requests

class TestTOCIntegration(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({
            'name': 'Test ',
            'email': 'desconhecido@example.com',
            'vat': '/',
            'street': 'Test Street',
            'city': 'Lisboa',
            'zip': '1000-001',
            'country_id': self.env.ref('base.pt').id,
            'toc_online_id': '6059876'
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
    def test_get_or_create_customer(self, mock_post, mock_get):
        access_token = 'dummy_token'

        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'data': []}

        mock_post.return_value.status_code = 201
        mock_post.return_value.json.return_value = {
            'data': {'id': 'toc_customer_id_123'}
        }

        toc_customer_id = self.move.get_or_create_customer_in_toconline(access_token, self.partner)
        print("Client id is : " , toc_customer_id)


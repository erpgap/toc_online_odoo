import logging
import requests
import json

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)



class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def create_payment_for_missing_receipt(self, missing_receipt):

        invoices = self.env['account.move'].search([
            ('toc_document_no', 'ilike', missing_receipt['document_no'])
        ])

        if not invoices:
            return False

        if len(invoices) > 1:
            return False

        invoice = invoices[0]

        if not invoice.toc_online_enabled:
            return False
        try:
            toc_receipt_ids = json.loads(invoice.toc_receipt_ids or "[]")
            if not isinstance(toc_receipt_ids, list):
                toc_receipt_ids = [toc_receipt_ids]
        except json.JSONDecodeError as e:
            toc_receipt_ids = []

        receipt_id_str = str(missing_receipt['receipt_id'])

        if receipt_id_str in [str(x) for x in toc_receipt_ids]:
            return False

        if invoice.state != 'posted':
            for line in invoice.invoice_line_ids:
                for tax in line.tax_ids:
                    if tax.amount == 0 and not invoice.tax_exemption_reason:
                        raise UserError(f"Cannot validate invoice {invoice.name} with VAT exemption without a reason.")
            invoice.action_post()

        receipt_data = self.get_receipt_data(missing_receipt['receipt_id'])

        if not isinstance(receipt_data, dict):
            return False

        receipt_date = receipt_data.get("date")
        amount = float(receipt_data.get("gross_total") or 0.0)

        if amount == 0.0:
            return False

        existing_payment = self.env['account.payment'].search([
            ('amount', '=', amount),
            ('date', '=', receipt_date),
            ('invoice_ids', 'in', invoice.id)
        ], limit=1)

        if existing_payment:
            return False

        journal = invoice.journal_id
        if journal.type not in ['bank', 'cash']:
            journal = self.env['account.journal'].search([
                ('type', 'in', ['bank', 'cash']),
                ('company_id', '=', invoice.company_id.id)
            ], limit=1)

        if not journal:
            raise UserError(_("No 'bank' or 'cash' type journals available."))

        payment_method_line = journal.inbound_payment_method_line_ids[:1]
        if not payment_method_line:
            raise UserError(f"Journal '{journal.name}' has no payment methods.")

        try:
            invoice._message_log(
                body=f"Payment TOC automatically created for receipt {receipt_id_str}"
            )

            register_pay = self.env['account.payment.register'].with_context(
                active_model='account.move',
                active_ids=[invoice.id]  # lista com 1 ID
            ).create({
                'payment_date': receipt_date,
                'journal_id': journal.id,
                'amount': amount,
                'payment_method_line_id': payment_method_line.id,
                'communication': f'TOC Payment: {missing_receipt["document_no"]}',
                'group_payment': False,
            })

            register_pay.action_create_payments()
            invoice._compute_amount()


            if receipt_id_str not in toc_receipt_ids:
                toc_receipt_ids.append(receipt_id_str)
                invoice.write({'toc_receipt_ids': json.dumps(toc_receipt_ids)})
                invoice.flush()
                invoice.invalidate_cache()


            return True

        except Exception as e:
            return False

    def get_receipt_data(self, receipt_id):
        company = self.company_id or self.env.company
        if not company.toc_online_enabled:
            return None
        try:
            access_token = self.env['toc.api'].get_access_token(company=company)
        except UserError as e:
            _logger.error("Failed to obtain TOConline access token: %s", e)
            return None
        if not access_token:
            _logger.error("Access token not found for company %s.", company.name)
            return None

        endpoint = f"{company._get_toc_api_url()}/api/v1/commercial_sales_receipts/{receipt_id}"

        try:
            response = self.env['toc.api'].toc_request(
                method='GET',
                url=endpoint,
                access_token=access_token,
            )

            data = response.json()

            if isinstance(data, list) and len(data) > 0:
                return data[0]
            elif isinstance(data, dict):
                return data
            else:
                return None

        except Exception as e:
            _logger.error(f"Error fetching receipt {receipt_id} from TOConline: {str(e)}")
            return None

from odoo import models, fields, api
import requests
import json
from odoo.exceptions import UserError
from odoo.addons.toc_invoice.utils import TOC_BASE_URL

class AccountPayment(models.Model):
    _inherit = 'account.payment'


    @api.model
    def sync_payments_from_toc(self):
        print(" Start TOC Sync --> Odoo")

        access_token = self.env['ir.config_parameter'].sudo().get_param('toc_online.access_token')
        if not access_token:
            print("TOConline token not defined.")
            return

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        endpoint = f"{TOC_BASE_URL}/api/v1/commercial_sales_documents"
        response = requests.get(endpoint, headers=headers)
        if response.status_code != 200:
            print(f"Error in TOC request: {response.status_code} - {response.text}")
            return

        docs = response.json()
        missing_receipts = []
        processed_receipts = set()

        for doc in docs:
            invoice_id = doc.get("id")
            receipt_ids = doc.get("receipts_ids") or []
            document_no = doc.get("document_no") or "N/A"

            for rid in receipt_ids:
                str_rid = str(rid)
                if str_rid in processed_receipts:
                    print(f" Receipt {rid} has already been processed, ignoring.")
                    continue

                all_invoices = self.env['account.move'].search([
                    ('toc_receipt_ids', '!=', False)
                ])
                already_registered = False

                for inv in all_invoices:
                    try:
                        ids_list = json.loads(inv.toc_receipt_ids or "[]")
                        if isinstance(ids_list, list):
                            if str_rid in [str(x) for x in ids_list]:
                                already_registered = True
                                print(f" Receipt {rid} already registered on the invoice{inv.name}")
                                break


                    except json.JSONDecodeError:
                        continue

                if already_registered:
                    continue

                missing = {
                    'receipt_id': rid,
                    'invoice_id': invoice_id,
                    'document_no': document_no,
                }

                created = self.create_payment_for_missing_receipt(missing)

                if created:
                    processed_receipts.add(str_rid)
                    missing_receipts.append(missing)

        print(" Synchronization completed.")
        return missing_receipts

    def create_payment_for_missing_receipt(self, missing_receipt):
        print(f"Trying to create payment for receipt: {missing_receipt['receipt_id']}")

        invoice = self.env['account.move'].search([
            ('toc_document_no', 'ilike', missing_receipt['document_no'])
        ], limit=1)

        if not invoice:
            print(f"No invoice found with toc_document_no = {missing_receipt['document_no']}")
            return False

        invoice = invoice.ensure_one()

        try:
            toc_receipt_ids = json.loads(invoice.toc_receipt_ids or "[]")
            print(f"List of toc_receipt_ids: {toc_receipt_ids}")
        except json.JSONDecodeError as e:
            print(f"Error loading receipt IDs: {e}")
            toc_receipt_ids = []

        receipt_id_str = str(missing_receipt['receipt_id'])
        try:
            toc_receipt_ids = json.loads(invoice.toc_receipt_ids or "[]")
            if not isinstance(toc_receipt_ids, list):
                toc_receipt_ids = [toc_receipt_ids]
        except json.JSONDecodeError as e:
            print(f"Error loading receipt IDs: {e}")
            toc_receipt_ids = []

        if receipt_id_str in [str(x) for x in toc_receipt_ids]:
            print(f"Receipt {receipt_id_str} already registered on the invoice {invoice.name}")
            return False

        if invoice.state != 'posted':
            print(f" Invoice '{invoice.name}'was not validated. Publishing...")
            invoice.action_post()

        receipt_data = self.get_receipt_data(missing_receipt['receipt_id'])

        if not isinstance(receipt_data, dict):
            print(f"Invalid receipt data.")
            return False

        receipt_date = receipt_data.get("date")
        amount = float(receipt_data.get("gross_total") or 0.0)

        existing_payment = self.env['account.payment'].search([
            ('amount', '=', amount),
            ('date', '=', receipt_date),
            ('invoice_ids', 'in', invoice.ids)
        ], limit=1)

        if existing_payment:
            print(f"There is already a payment for the receipt {missing_receipt['receipt_id']} on the invoice {invoice.name}")
            return False

        if amount == 0.0:
            print(f" Receipt amount is zero. Ignored.")
            return False

        journal = invoice.journal_id
        if journal.type not in ['bank', 'cash']:
            journal = self.env['account.journal'].search([
                ('type', 'in', ['bank', 'cash']),
                ('company_id', '=', invoice.company_id.id)
            ], limit=1)
            print(f"Replaced diary: {journal.name}")

        if not journal:
            raise UserError("No 'bank' or 'cash' type journals available.")

        payment_method_line = journal.inbound_payment_method_line_ids[:1]
        if not payment_method_line:
            raise UserError(f"Daily '{journal.name}' no payment methods.")

        try:
            invoice._message_log(
                body=f" Payment TOC automatically created for receipt{receipt_id_str}"
            )

            register_pay = self.env['account.payment.register'].with_context(
                active_model='account.move',
                active_ids=invoice.ids
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

            if invoice.payment_state in ['paid', 'in_payment'] or invoice.amount_residual == 0.0:
                print(f" The invoice{invoice.name} is now paid or partially paid.")
            else:
                print(f"The invoice {invoice.name} remains with open value: {invoice.amount_residual}")

            if receipt_id_str not in toc_receipt_ids:
                toc_receipt_ids.append(receipt_id_str)
                invoice.write({'toc_receipt_ids': json.dumps(toc_receipt_ids)})
                invoice.flush()
                invoice.invalidate_cache()
            else:
                print(f" Receipt {receipt_id_str} it was already on the invoice {invoice.name}")

            return True

        except Exception as e:
            print(f"Error creating payment: {e}")
            return False

    def get_receipt_data(self, receipt_id):
        access_token = self.env['ir.config_parameter'].sudo().get_param('toc_online.access_token')
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        endpoint = f"{TOC_BASE_URL}/api/v1/commercial_sales_receipts/{receipt_id}"

        response = requests.get(endpoint, headers=headers)

        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            elif isinstance(data, dict):
                return data
            else:
                print(f"Unexpected format for receipt {receipt_id}")
                return None
        else:
            print(f" Failed to fetch receipt {receipt_id}. Status: {response.status_code} - {response.text}")
            return None
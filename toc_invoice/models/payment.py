from odoo import models, fields, api
import requests
import json
from odoo.exceptions import UserError

class AccountPayment(models.Model):
    _inherit = 'account.payment'

    base_url = 'https://api9.toconline.pt'

    @api.model
    def sync_payments_from_toc(self):
        print(" Início da sincronização TOC --> Odoo")

        access_token = self.env['toc.api'].get_access_token()
        if not access_token:
            print("Token TOConline não definido.")
            return

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        endpoint = f"{self.base_url}/api/v1/commercial_sales_documents"
        print("Endpoint utilizado:", endpoint)
        response = requests.get(endpoint, headers=headers)
        if response.status_code != 200:
            print(f"❌ Erro na requisição TOC: {response.status_code} - {response.text}")
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
                    #print(f" Recibo {rid} já foi processado, ignorando.")
                    continue

                # Verifica se o recibo já está em alguma fatura
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
                                #print(f" Recibo {rid} já registado na fatura {inv.name}")
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

                print(f"Fatura TOC: {document_no} | ID: {invoice_id} |  Recibo em falta: {rid}")
                created = self.create_payment_for_missing_receipt(missing)

                if created:
                    processed_receipts.add(str_rid)
                    missing_receipts.append(missing)

        print("✅ Sincronização finalizada.")
        return missing_receipts

    def create_payment_for_missing_receipt(self, missing_receipt):
        print(f"🔍 Tentando criar pagamento para recibo: {missing_receipt['receipt_id']}")

        invoice = self.env['account.move'].search([
            ('toc_document_no', 'ilike', missing_receipt['document_no'])
        ], limit=1)

        if not invoice:
            print(f"❌ Nenhuma fatura encontrada com toc_document_no = {missing_receipt['document_no']}")
            return False

        invoice = invoice.ensure_one()
        print(f"✅ Invoice singleton confirmado: {invoice}, ID: {invoice.id}")
        print(f"✅ Invoice.ids: {invoice.ids}, len: {len(invoice)}")

        print(f"Fatura encontrada: {invoice.name}")

        try:
            toc_receipt_ids = json.loads(invoice.toc_receipt_ids or "[]")
            print(f"Lista de toc_receipt_ids: {toc_receipt_ids}")
        except json.JSONDecodeError as e:
            print(f"Erro ao carregar os IDs dos recibos: {e}")
            toc_receipt_ids = []

        receipt_id_str = str(missing_receipt['receipt_id'])
        try:
            toc_receipt_ids = json.loads(invoice.toc_receipt_ids or "[]")
            if not isinstance(toc_receipt_ids, list):
                toc_receipt_ids = [toc_receipt_ids]
        except json.JSONDecodeError as e:
            print(f"Erro ao carregar os IDs dos recibos: {e}")
            toc_receipt_ids = []

        if receipt_id_str in [str(x) for x in toc_receipt_ids]:
            print(f"Recibo {receipt_id_str} já registado na fatura {invoice.name}")
            return False

        if invoice.state != 'posted':
            print(f" Fatura '{invoice.name}' não estava validada. Publicando...")
            invoice.action_post()

        receipt_data = self.get_receipt_data(missing_receipt['receipt_id'])
        print(" Verificação de receipt_data:", receipt_data)

        if not isinstance(receipt_data, dict):
            print(f"❌ Dados do recibo inválidos.")
            return False

        receipt_date = receipt_data.get("date")
        amount = float(receipt_data.get("gross_total") or 0.0)

        existing_payment = self.env['account.payment'].search([
            ('amount', '=', amount),
            ('date', '=', receipt_date),
            ('invoice_ids', 'in', invoice.ids)
        ], limit=1)

        if existing_payment:
            print(f" Já existe um pagamento para o recibo {missing_receipt['receipt_id']} na fatura {invoice.name}")
            return False

        print(f" Data do recibo: {receipt_date}, 💰 Valor: {amount}")
        if amount == 0.0:
            print(f" Valor do recibo é zero. Ignorado.")
            return False

        journal = invoice.journal_id
        if journal.type not in ['bank', 'cash']:
            journal = self.env['account.journal'].search([
                ('type', 'in', ['bank', 'cash']),
                ('company_id', '=', invoice.company_id.id)
            ], limit=1)
            print(f" Diário substituído: {journal.name}")

        if not journal:
            raise UserError("Nenhum diário do tipo 'bank' ou 'cash' disponível.")

        payment_method_line = journal.inbound_payment_method_line_ids[:1]
        if not payment_method_line:
            raise UserError(f"Diário '{journal.name}' sem métodos de pagamento.")

        try:
            invoice._message_log(
                body=f" Pagamento TOC criado automaticamente para o recibo {receipt_id_str}"
            )

            register_pay = self.env['account.payment.register'].with_context(
                active_model='account.move',
                active_ids=invoice.ids
            ).create({
                'payment_date': receipt_date,
                'journal_id': journal.id,
                'amount': amount,
                'payment_method_line_id': payment_method_line.id,
                'communication': f'Pagamento TOC: {missing_receipt["document_no"]}',
                'group_payment': False,
            })

            print(f" Registrando pagamento para a fatura {invoice.name}, valor: {amount}")
            register_pay.action_create_payments()
            print(f"✅ Pagamento registado na fatura {invoice.name} via wizard")

            invoice._compute_amount()

            if invoice.payment_state in ['paid', 'in_payment'] or invoice.amount_residual == 0.0:
                print(f"✅ A fatura {invoice.name} está agora paga ou parcialmente paga.")
            else:
                print(f"⚠️ A fatura {invoice.name} continua com valor em aberto: {invoice.amount_residual}")

            # Adiciona o recibo à lista
            if receipt_id_str not in toc_receipt_ids:
                toc_receipt_ids.append(receipt_id_str)
                invoice.write({'toc_receipt_ids': json.dumps(toc_receipt_ids)})
                print(f" Atualizando toc_receipt_ids: {invoice.toc_receipt_ids}")
                invoice.flush()
                invoice.invalidate_cache()
                print(f" Recibo {receipt_id_str} adicionado à fatura {invoice.name}")
                print(f" Lista atualizada de recibos: {invoice.toc_receipt_ids}")
            else:
                print(f" Recibo {receipt_id_str} já estava na fatura {invoice.name}")

            return True

        except Exception as e:
            print(f"❌ Erro ao criar pagamento: {e}")
            return False

    def get_receipt_data(self, receipt_id):
        access_token = self.env['toc.api'].get_access_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        endpoint = f"{self.base_url}/api/v1/commercial_sales_receipts/{receipt_id}"

        print(" Endpoint final:", endpoint)
        response = requests.get(endpoint, headers=headers)

        if response.status_code == 200:
            data = response.json()
            print(f" Dados do recibo {receipt_id}:", data)
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            elif isinstance(data, dict):
                return data
            else:
                print(f"❌ Formato inesperado para o recibo {receipt_id}")
                return None
        else:
            print(f" Falha ao buscar recibo {receipt_id}. Status: {response.status_code} - {response.text}")
            return None
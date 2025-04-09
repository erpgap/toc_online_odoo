import json
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import json

class AccountMove(models.Model):
    _inherit = 'account.move'

    toc_status = fields.Selection([
        ('draft', 'Rascunho'),
        ('sent', 'Enviado'),
        ('error', 'Erro')
    ], string="Status TOConline", default='draft')

    toc_status_credit_note = fields.Selection([
        ('draft', 'Rascunho'),
        ('sent', 'Enviado'),
        ('error', 'Erro')
    ], string="Status TOConline", default='draft')

    toc_invoice_url = fields.Char(string="URL Fatura TOConline")
    base_url = 'https://api9.toconline.pt'
    checkbox = fields.Boolean(string="Checkbox marcada", default=True)
    toc_document_no = fields.Char(string="Número do Documento TOConline")
    toc_document_no_credit_note = fields.Char(string="Número da nota de crédito TOC")

    toc_display_number = fields.Char(string="Nº TOC (Visualização)", compute="_compute_toc_display_number", store=True)

    credit_note_total_value = fields.Float(string="Valor Total Nota de Crédito")

    toc_total_display = fields.Float(
        string="Total TOConline (Dinâmico)",
        compute="_compute_toc_total_display",
        store=False  # Não precisa ser armazenado, pois é apenas para exibição
    )




    def set_value_credit_note(self, aux):
        for record in self:
            record.credit_note_total_value = aux
        return aux

    def get_value_credit_note(self):
        return self.credit_note_total_value

    @api.depends('toc_document_no', 'toc_document_no_credit_note', 'move_type')
    def _compute_toc_display_number(self):
        for move in self:
            if move.move_type in ('out_refund', 'in_refund'):
                move.toc_display_number = move.toc_document_no_credit_note or '/'
            else:
                move.toc_display_number = move.toc_document_no or '/'

    @api.depends('amount_total_in_currency_signed', 'credit_note_total_value', 'move_type')
    def _compute_toc_total_display(self):
        for move in self:
            if move.move_type in ('out_refund', 'in_refund'):
                # Mostra valor negativo nas notas de crédito
                move.toc_total_display = -abs(move.credit_note_total_value)
            else:
                move.toc_total_display = move.amount_total_in_currency_signed

    def get_base_url(self):
        return  self.base_url

    def get_toc_status_credit_note(self):
        return  self.toc_status_credit_note

    def set_toc_status_credit_note(self , teste):

        self.toc_status_credit_note = teste

    def get_ID_invoice(self):
        self.ensure_one()
        return self.toc_document_no

    def getStateCompany(self):
        """
        Retorna o estado da empresa (obtido do parceiro da empresa).
        """
        companies = self.env['res.company'].search([])
        portuguese_company = companies.filtered(lambda c: c.country_id.code == 'PT')
        if portuguese_company:
            return portuguese_company.partner_id.state_id.name
        else:
            print("Nenhuma empresa portuguesa encontrada")
            return False

    def get_taxes_from_toconline(self, access_token):
        """
        Busca as taxas de IVA disponíveis no TOConline.
        """
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        url = f"{self.base_url}/api/taxes"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('data', [])
        else:
            raise UserError(f"Error fetching rates from TOConline: {response.text}")

    def get_tax_code(self, tax_percentage, tax_region, taxes_data):
        """
        Mapeia o valor da taxa e a região para o código de imposto correto no TOConline.
        """
        for tax in taxes_data:
            attributes = tax["attributes"]
            if (float(attributes["tax_percentage"]) == tax_percentage and
                    attributes["tax_country_region"] == tax_region):
                return attributes["tax_code"]
        raise UserError(f"Tax {tax_percentage}% not found for the region {tax_region}.")

    def get_tax_info(self, percentage, region, tax_list):
        """
        Retorna tax_code e tax_percentage vindo do TOConline, baseado no valor local e região.
        """
        for tax in tax_list:
            tax_attr = tax["attributes"]
            if float(tax_attr["tax_percentage"]) == float(percentage) and tax_attr["tax_country_region"] == region:
                return {
                    "code": tax_attr["tax_code"],
                    "percentage": tax_attr["tax_percentage"]
                }
        raise UserError(f"Não foi encontrada uma taxa com {percentage}% para a região {region}.")


    def get_conversion_rate_to_euro(self, invoice_currency):
        """
        Obtém a taxa de conversão para EUR usando a conversão nativa do Odoo.
        Se a fatura estiver postada, usa o valor calculado (invoice_currency_rate);
        caso contrário, usa o método _convert da moeda.
        """
        if invoice_currency == 'EUR':
            return 1  # Já está em EUR

        # Obtem os objetos de moeda
        currency_obj = self.env['res.currency'].search([('name', '=', invoice_currency)], limit=1)
        euro_currency = self.env['res.currency'].search([('name', '=', 'EUR')], limit=1)
        if not currency_obj or not euro_currency:
            raise UserError(f"A moeda {invoice_currency} ou EUR não foi encontrada no Odoo.")

        if self.state == "posted":
            # Se estiver postada, utiliza a taxa calculada
            if self.invoice_currency_rate:
                return self.invoice_currency_rate
            else:
                raise UserError(
                    f"Nenhuma taxa de câmbio encontrada para {invoice_currency}. Verifique as configurações."
                )

        # Para faturas não postadas, utiliza a taxa do método _convert com o contexto de data
        date = self.invoice_date or fields.Date.today()
        conversion_rate = currency_obj.with_context(date=date)._convert(1, euro_currency, self.env.company, date)
        if conversion_rate <= 0:
            raise UserError(f"Não foi possível obter a taxa de conversão para {invoice_currency}.")
        return conversion_rate

    def get_or_create_customer_in_toconline(self, access_token, partner):
        """
        Verifica se o cliente já existe no TOConline (via toc_online_id, NIF ou e-mail).
        Se não existir, cria o cliente, garantindo que não haja duplicatas.
        """
        # 1. Se já tem ID no TOConline, retorna imediatamente
        if partner.toc_online_id:
            print(f"✅ Cliente já possui ID no TOConline: {partner.toc_online_id}")
            return partner.toc_online_id

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        tax_number = partner.vat.replace(" ", "").strip() if partner.vat else "Desconhecido"
        email = partner.email.strip() if partner.email else ""
        customers = []

        # 2. Pesquisa por NIF (apenas se válido e não for "/")
        if tax_number != "Desconhecido" and tax_number.isdigit() and len(tax_number) == 9:
            search_url = f"{self.base_url}/api/customers?filter[tax_registration_number]={tax_number}"
            response = requests.get(search_url, headers=headers)
            if response.status_code == 200:
                customers = response.json().get('data', [])
                if customers:
                    print(f"✅ Cliente encontrado via NIF: {customers[0]['attributes']['business_name']}")
                    partner.sudo().write({'toc_online_id': customers[0]["id"]})
                    return customers[0]["id"]

        # 3. Se não tem NIF válido ou não foi encontrado, pesquisa por e-mail (obrigatório)
        if not customers and email:
            search_url = f"{self.base_url}/api/customers?filter[email]={email}"
            response = requests.get(search_url, headers=headers)
            if response.status_code == 200:
                customers = response.json().get('data', [])
                if customers:
                    print(f"✅ Cliente encontrado via e-mail: {customers[0]['attributes']['business_name']}")
                    partner.sudo().write({'toc_online_id': customers[0]["id"]})
                    return customers[0]["id"]

        # 4. Se não encontrou nem por NIF nem por e-mail, cria um novo
        create_url = f"{self.base_url}/api/customers"
        customer_payload = {
            "data": {
                "type": "customers",
                "attributes": {
                    "tax_registration_number": tax_number ,
                    "business_name": partner.name,
                    "contact_name": partner.name,
                    "website": partner.website or "",
                    "phone_number": partner.phone or "",
                    "mobile_number": partner.mobile or "",
                    "email": email,
                    "observations": "",
                    "internal_observations": "",
                    "is_tax_exempt": False,
                    "active": True,
                    "country_iso_alpha_2": partner.country_id.code if partner.country_id else None
                }
            }
        }
        print("este é o nosso produto ")
        print(customer_payload)

        print("📤 Criando novo cliente no TOConline...")
        response = requests.post(create_url, json=customer_payload, headers=headers)

        if response.status_code in (200, 201):
            customer_id = response.json()["data"]["id"]
            print(f"✅ Cliente criado com sucesso (ID: {customer_id})")
            partner.sudo().write({'toc_online_id': customer_id})
            return customer_id
        else:
            error_msg = response.text
            if "already exists" in error_msg.lower():
                raise UserError(
                    _("❌ O cliente já existe no TOConline, mas não foi possível vinculá-lo automaticamente."))
            else:
                raise UserError(_("❌ Erro ao criar cliente no TOConline: %s") % error_msg)
    def get_or_create_product_in_toconline(self, access_token, product):
        """
        Verifica se o produto já existe no TOConline.
        Caso contrário, cria-o e retorna o ID do produto.
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
        search_url = f"{self.base_url}/api/products?filter[item_code]={product.default_code}"
        response = requests.get(search_url, headers=headers)
        if response.status_code == 200:
            products = response.json().get('data', [])
            if products:
                print(f"Product found on TOConline: {products[0]['attributes']['item_code']}")
                return products[0]["id"]
        # Se não encontrado, cria o produto
        print(f"Product not found; creating new product: {product.name}")
        create_url = f"{self.base_url}/api/products"
        product_payload = {
            "data": {
                "type": "products",
                "attributes": {
                    "type": "Product",
                    "item_code": product.default_code,
                    "item_description": product.name,
                    "sales_price": product.list_price,
                    "sales_price_includes_vat": False,
                }
            }
        }
        print(f"📦 Payload enviado:\n{json.dumps(product_payload, indent=4, ensure_ascii=False)}")
        response = requests.post(create_url, json=product_payload, headers=headers)
        if response.status_code == 200:
            data = response.json()
            product_id = data.get("data", {}).get("id")
            print(f"Product created successfully! Product ID: {product_id}")
            return product_id
        else:
            raise UserError(_("Error creating product in TOConline: %s") % response.text)

    def action_send_invoice_to_toconline(self):
        """
        Envia os dados da fatura para o TOConline.
        Caso o token esteja expirado, tenta renová-lo antes de enviar.
        """


        for record in self:
            if record.toc_status == 'sent':
                raise UserError("This invoice has already been sent to TOConline.")
            if record.state != 'posted':
                raise UserError("Only published invoices can be submitted.")

            if record.move_type in ('out_refund', 'in_refund'):  # Nota de crédito
                record.toc_status = 'draft'  # Ou defina como 'sent' se necessário
            elif record.move_type == 'out_invoice':  # Fatura
                if record.state != 'posted':
                    raise UserError("Only published invoices can be submitted.")
                record.toc_status = 'draft'  # Inicia como rascunho antes de enviar.


            # Obter token de acesso
            url_authorization_code = self.env['toc.api'].get_authorization_url()
            client_id = self.env['ir.config_parameter'].sudo().get_param('toc_online.client_id')
            authorization_code = self.env['toc.api']._extract_authorization_code_from_url(url_authorization_code)
            if not authorization_code:
                raise UserError(
                    f"Error getting authorization code. URL: {url_authorization_code}, Client ID: {client_id}"
                )
            tokens = self.env['toc.api']._get_tokens(authorization_code)

            for record in self:
                document_no = record.get_ID_invoice()
                print(f"este é o numero da minha faturaaaaaaaaaaa {document_no}")
            if "error" in tokens:
                raise UserError(f"Error getting token code: {tokens['error']}")
            access_token = tokens.get("access_token")

            if access_token:
                self.env['ir.config_parameter'].sudo().set_param('toc_online.access_token' , access_token)

            if not access_token:
                raise UserError("Could not get access token.")

            toc_endpoint = f"{self.base_url}/api/v1/commercial_sales_documents"
            partner = record.partner_id
            if not all([partner.name, partner.street, partner.city, partner.country_id, partner.zip]):
                raise UserError("Customer must have name, address, city, country and postal code filled in.")
            customer_id = self.get_or_create_customer_in_toconline(access_token, partner)

            # Determina o estado da empresa e mapeia para a região fiscal
            state_company = self.getStateCompany()
            region_map = {
                "Madeira": "PT-MA",
                "Açores": "PT-AC",
                "Continente": "PT"
            }
            tax_region = region_map.get(state_company, "PT")

            print("está a a nossa taxa ---",tax_region)

            taxes_data = self.get_taxes_from_toconline(access_token)
            filtered_taxes = [
                tax for tax in taxes_data
                if tax["attributes"]["tax_country_region"] == tax_region
            ]

            print("estas são as taxas --------------0")
            print(taxes_data)
            print("*-------------------*")
            print(filtered_taxes)
            print("fim------------------------")
            global_exemption_reason = None
            lines = []

            for line in record.invoice_line_ids:
                product_id = self.get_or_create_product_in_toconline(access_token, line.product_id)
                if line.tax_ids:
                    tax = line.tax_ids[0]
                    tax_percentage = tax.amount
                else:
                    tax_percentage = 0
                tax_info = self.get_tax_info(tax_percentage, tax_region, filtered_taxes)
                tax_code = tax_info["code"]
                tax_percentage_toc = tax_info["percentage"]

                if tax_percentage == 0 and not global_exemption_reason:
                    if record.l10npt_vat_exempt_reason:
                        global_exemption_reason = record.l10npt_vat_exempt_reason.id
                    else:
                        raise UserError("The VAT rate is 0%, but no exemption reason was given.")

                print("mostra aqui a taxa----",tax_percentage_toc)



                lines.append({
                    "item_id": product_id,
                    "item_code": line.product_id.default_code,
                    "description": line.product_id.name,
                    "quantity": line.quantity,
                    "unit_price":line.price_unit,
                    "tax_code": tax_code,
                    "tax_percentage": tax_percentage_toc,
                    "tax_country_region": tax_region,
                    "item_type": "Product",
                    "exemption_reason": None,
                })


            print("estas são as lines -----------------")
            print(lines)
            print("-----------------------------***---------")
            currency_obj = self.currency_id  # Moeda da fatura
            company_currency = self.company_id.currency_id  # Moeda da empresa (normalmente EUR)
            date = self.invoice_date or fields.Date.today()

            conversion_rate = currency_obj._get_conversion_rate(currency_obj, company_currency, self.company_id, date)

            payload = {
                "document_type": "FT",
                "date": record.invoice_date.strftime("%Y-%m-%d") if record.invoice_date else "",
                "finalize": 0,
                "customer_tax_registration_number": partner.vat.strip() if partner.vat and partner.vat.strip() else "Desconhecido",
                "customer_business_name": partner.name,
                "customer_address_detail": partner.street or "",
                "customer_postcode": partner.zip or "",
                "customer_city": partner.city or "",
                "customer_tax_country_region": tax_region,
                "customer_country": partner.country_id.code or "",
                "due_date": record.invoice_date_due.strftime("%Y-%m-%d") if record.invoice_date_due else "",
                "payment_mechanism": "MO",
                "vat_included_prices": record.journal_id.vat_included_prices if hasattr(record.journal_id, 'vat_included_prices') else False,
                "operation_country": tax_region,
                "currency_iso_code": record.currency_id.name,
                "currency_conversion_rate": conversion_rate,
                "retention": 7.5,
                "retention_type": "IRS",
                "apply_retention_when_paid": True,
                "notes": "Notas ao documento",
                "tax_exemption_reason_id": global_exemption_reason,
                "lines": lines,
            }

            print(payload)
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}"
            }
            response = requests.post(toc_endpoint, json=payload, headers=headers, timeout=120)
            print(f"Resposta do envio: {response.status_code}")

            print(f"Resposta do envio: {response.text}")

            if response.status_code != 200:
                raise UserError(
                    f"Erro ao enviar a fatura para o TOConline. Status Code: {response.status_code}. Corpo da resposta: {response.text}"
                )

            print(f"teste 1 {self.toc_document_no}")

            data = response.json()  # <- Certifique-se de que esta linha vem antes de usar 'data'
            document_no = data.get('document_no', '')

            print(f"teste 2 {document_no}")
            record.write({
                'toc_status': 'sent',
                'toc_invoice_url': data.get('invoice_url', ''),
                'toc_document_no': document_no
            })

            self.env.cr.commit()
            print(f"teste 11 {self.toc_document_no}")

            variavelteste = self.get_ID_invoice()
            print(f"teste 111 {variavelteste}")

    def get_customer_id(self, access_token, tax_number=None, email=None):
        """
        Busca o ID de um cliente no TOConline por NIF ou email.
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
        customers = []
        if tax_number and tax_number.isdigit() and len(tax_number) == 9:
            search_url = f"{self.base_url}/api/customers?filter[tax_registration_number]={tax_number}"
            response = requests.get(search_url, headers=headers)
            if response.status_code == 200:
                customers = response.json().get('data', [])
        if not customers and email:
            search_url = f"{self.base_url}/api/customers?filter[email]={email}"
            response = requests.get(search_url, headers=headers)
            if response.status_code == 200:
                customers = response.json().get('data', [])
        if customers:
            print(f"Client found on TOConline: {customers[0]['attributes']['business_name']}")
            return customers[0]["id"]
        return None

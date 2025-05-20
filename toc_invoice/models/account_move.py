import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
from odoo.addons.toc_invoice.utils import TOC_BASE_URL

class AccountMove(models.Model):
    _inherit = 'account.move'

    toc_status = fields.Selection([
        ('draft', 'draft'),
        ('sent', 'sent'),
        ('error', 'Error'),
        ('cancelled', 'cancelled'),

    ], string="TOConline Status", default='draft')

    toc_status_credit_note = fields.Selection([
        ('draft', 'draft'),
        ('sent', 'sent'),
        ('error', 'Error')
    ], string="TOConline Status", default='draft')


    toc_invoice_url = fields.Char(string="TOConline Invoice URL")
    checkbox = fields.Boolean(string="Checkbox marked", default=True)
    toc_document_no = fields.Char(string="TOConline Document Number")
    toc_document_id = fields.Char(string="TOConline Document Number")
    toc_document_no_credit_note = fields.Char(string="Credit Note Number TOConline")

    toc_display_number = fields.Char(string="TOConline Number. (Visualization)", compute="_compute_toc_display_number", store=True)

    credit_note_total_value = fields.Float(string="Valor Total Nota de Crédito")

    toc_total_display = fields.Float(
        string="Total TOConline (Dynamic)",
        compute="_compute_toc_total_display",
        store=False
    )

    toc_receipt_ids = fields.Text(
        string="TOConline Sales Receipt IDs",
        help="List of payment receipt IDs associated with TOConline",
    )

    cancellation_reason = fields.Char(string="reason for invoice cancellation")
    cancellation_date = fields.Date(string="Date of cancellation")


    def set_value_credit_note(self, aux):
        for record in self:
            record.credit_note_total_value = aux
        return aux

    def get_invoice_number(self):
        for rec in self:
            _logger = logging.getLogger(__name__)
            _logger.info("ID: %s | Número: %s | Estado: %s", rec.id, rec.name, rec.state)

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
                move.toc_total_display = -abs(move.credit_note_total_value)
            else:
                move.toc_total_display = move.amount_total_in_currency_signed

    def get_base_url(self):
        return  TOC_BASE_URL

    def get_toc_status_credit_note(self):
        return  self.toc_status_credit_note

    def set_toc_status_credit_note(self , teste):

        self.toc_status_credit_note = teste

    def get_ID_invoice(self):
        self.ensure_one()
        return self.toc_document_no

    def getStateCompany(self):
        """
        Returns the company state (obtained from the company partner).
        """
        companies = self.env['res.company'].search([])
        portuguese_company = companies.filtered(lambda c: c.country_id.code == 'PT')
        if portuguese_company:
            return portuguese_company.partner_id.state_id.name
        else:
            print(_("No Portuguese companies found"))
            return False

    def get_document_id_by_number(self, access_token, document_no):
        """
       Searches for a document by its number in TOConline and returns the corresponding ID.
        """

        url = f"{TOC_BASE_URL}/api/v1/commercial_sales_documents/"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            raise UserError(_(f"Error retrieving documents from TOConline: {response.text}"))

        documents = response.json()

        if isinstance(documents, dict) and 'data' in documents:
            documents = documents['data']

        for doc in documents:
            if doc.get("document_no") == document_no:
                return doc.get("id")

        raise UserError(_(f"Document with number {document_no} not found in TOConline."))

    def get_user_id_by_number_invoice(self, access_token, document_no):
        """
            Searches for a document by its number in TOConline and returns the corresponding ID.
        """

        url = f"{TOC_BASE_URL}/api/v1/commercial_sales_documents/"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            raise UserError(_(f"Error retrieving documents from TOConline: {response.text}"))

        documents = response.json()

        if isinstance(documents, dict) and 'data' in documents:
            documents = documents['data']

        for doc in documents:
            if doc.get("document_no") == document_no:
                return doc.get("user_id")

        raise UserError(_(f"Document with number {document_no}not found in TOConline."))

    def get_document_field_by_number(self, access_token, document_no, field):
        """
       Searches for a document by its number in TOConline and returns the value of the specified field.

        :param access_token: API access token
        :param document_no: Document number to search for
        :param field: Field to extract from the document (e.g. "id", "user_id", "country_id")
        :return: Field value if found
        """

        url = f"{TOC_BASE_URL}/api/v1/commercial_sales_documents/"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            raise UserError(_(f"Error retrieving documents from TOConline: {response.text}"))

        documents = response.json()

        if isinstance(documents, dict) and 'data' in documents:
            documents = documents['data']

        for doc in documents:
            if doc.get("document_no") == document_no:
                return doc.get(field)

        raise UserError(_(f"Document with number {document_no} not found in TOConline."))

    def get_taxes_from_toconline(self, access_token):
        """
            Search for available VAT rates on TOConline.
        """
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        url = f"{TOC_BASE_URL}/api/taxes"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('data', [])
        else:
            raise UserError(_(f"Error fetching rates from TOConline: {response.text}"))

    def get_tax_code(self, tax_percentage, tax_region, taxes_data):
        """
        Maps the tax amount and region to the correct tax code in TOConline.
        """
        for tax in taxes_data:
            attributes = tax["attributes"]
            if (float(attributes["tax_percentage"]) == tax_percentage and
                    attributes["tax_country_region"] == tax_region):
                return attributes["tax_code"]
        raise UserError(_(f"Tax {tax_percentage}% not found for the region {tax_region}."))

    def get_tax_info(self, percentage, region, tax_list):
        """
        Returns tax_code, tax_percentage, and id from TOConline, based on local value and region.
        """
        for tax in tax_list:
            tax_attr = tax["attributes"]
            if float(tax_attr["tax_percentage"]) == float(percentage) and tax_attr["tax_country_region"] == region:
                return {
                    "code": tax_attr["tax_code"],
                    "percentage": tax_attr["tax_percentage"],
                    "id": tax["id"]
                }
        raise UserError(_(f"No rate was found with {percentage}% for the region {region}."))



    def get_conversion_rate_to_euro(self, invoice_currency):
        """
        Gets the conversion rate to EUR using Odoo's native conversion.
        If the invoice is posted, uses the calculated value (invoice_currency_rate);
        otherwise, uses the currency's _convert method.
        """
        if invoice_currency == 'EUR':
            return 1

        currency_obj = self.env['res.currency'].search([('name', '=', invoice_currency)], limit=1)
        euro_currency = self.env['res.currency'].search([('name', '=', 'EUR')], limit=1)
        if not currency_obj or not euro_currency:
            raise UserError(_(f"The currency {invoice_currency} or EUR was not found in Odoo."))

        if self.state == "posted":
            if self.invoice_currency_rate:
                return self.invoice_currency_rate
            else:
                raise UserError(_(
                        f"No exchange rates found for {invoice_currency}. Check settings.")
                )

        date = self.invoice_date or fields.Date.today()
        conversion_rate = currency_obj.with_context(date=date)._convert(1, euro_currency, self.env.company, date)
        if conversion_rate <= 0:
            raise UserError(f"Unable to get conversion rate for{invoice_currency}.")
        return conversion_rate

    def get_or_create_customer_in_toconline(self, access_token, partner):
        """
        Checks if the client already exists in TOConline (via toc_online_id, NIF or email).
        If it does not exist, it creates the client, ensuring that there are no duplicates.
        """

        if partner.toc_online_id:
            print(_(f"Client already has an ID in TOConline: {partner.toc_online_id}"))
            return partner.toc_online_id

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        tax_number = partner.vat.replace(" ", "").strip() if partner.vat else "Desconhecido"
        email = partner.email.strip() if partner.email else ""
        customers = []

        if tax_number != "Desconhecido" and tax_number.isdigit() and len(tax_number) == 9:
            search_url = f"{TOC_BASE_URL}/api/customers?filter[tax_registration_number]={tax_number}"
            response = requests.get(search_url, headers=headers)
            if response.status_code == 200:
                customers = response.json().get('data', [])
                if customers:
                    print(_(f"Customer found via NIF: {customers[0]['attributes']['business_name']}"))
                    partner.sudo().write({'toc_online_id': customers[0]["id"]})
                    return customers[0]["id"]

        if not customers and email:
            search_url = f"{TOC_BASE_URL}/api/customers?filter[email]={email}"
            response = requests.get(search_url, headers=headers)
            if response.status_code == 200:
                customers = response.json().get('data', [])
                if customers:
                    print(f"Customer found via email: {customers[0]['attributes']['business_name']}")
                    partner.sudo().write({'toc_online_id': customers[0]["id"]})
                    return customers[0]["id"]

        create_url = f"{TOC_BASE_URL}/api/customers"
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

        response = requests.post(create_url, json=customer_payload, headers=headers)

        if response.status_code in (200, 201):
            customer_id = response.json()["data"]["id"]
            print(f"Client created successfully(ID: {customer_id})")
            partner.sudo().write({'toc_online_id': customer_id})
            return customer_id
        else:
            error_msg = response.text
            if "already exists" in error_msg.lower():
                raise UserError(
                    _(" The client already exists in TOConline, but it was not possible to link it automatically."))
            else:
                raise UserError(_(" Error creating client in TOConline: %s") % error_msg)

    def get_or_create_product_in_toconline(self, access_token, product):

        if not product.default_code:
            raise UserError(_("Product code (default_code) is empty."))

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
        search_url = f"{TOC_BASE_URL}/api/products?filter[item_code]={product.default_code}"
        response = requests.get(search_url, headers=headers)

        if response.status_code == 200:
            products = response.json().get('data', [])
            if products:
                return products[0]["id"]

        if product.list_price is None:
            raise UserError(_(f"The selling price (list_price) of the product {product.name} is empty."))
        create_url = f"{TOC_BASE_URL}/api/products"
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

        response = requests.post(create_url, json=product_payload, headers=headers)

        if response.status_code in (200, 201):
            data = response.json()
            product_id = data.get("data", {}).get("id")
            if not product_id:
                raise UserError(_(f"Product created, but ID was not returned: {data}"))
            return product_id
        else:
            raise UserError(_("Error creating product in TOConline: %s") % response.text)

    def action_send_invoice_to_toconline(self):
        """
        Sends all posted invoices to TOConline that haven't been sent yet.
        """
        invoices_to_send = self.env['account.move'].search([
            ('state', '=', 'posted'),
            ('toc_status', '!=', 'sent'),
            ('move_type', '=', 'out_invoice'),
        ])

        if not invoices_to_send:
            raise UserError(_("No invoices to send."))

        for record in invoices_to_send:
            # Preparação do status
            record.toc_status = 'draft'

            access_token = self.env['toc.api'].get_access_token()
            print("este é o access ", access_token)
            if not access_token:
                raise UserError(_("Could not get or refresh access token."))

            toc_endpoint = f"{TOC_BASE_URL}/api/v1/commercial_sales_documents"
            partner = record.partner_id
            if not all([partner.name, partner.street, partner.city, partner.country_id, partner.zip]):
                raise UserError(_("Customer must have name, address, city, country and postal code filled in."))

            customer_id = self.get_or_create_customer_in_toconline(access_token, partner)
            empresa_id = self.env.company.id

            state_company = self.getStateCompany()
            region_map = {
                "Madeira": "PT-MA",
                "Açores": "PT-AC",
                "Continente": "PT"
            }
            tax_region = region_map.get(state_company, "PT")
            taxes_data = self.get_taxes_from_toconline(access_token)
            filtered_taxes = [
                tax for tax in taxes_data
                if tax["attributes"]["tax_country_region"] == tax_region
            ]

            global_exemption_reason = None
            lines = []

            for line in record.invoice_line_ids:
                product_id = self.get_or_create_product_in_toconline(access_token, line.product_id)
                tax_percentage = line.tax_ids[0].amount if line.tax_ids else 0

                tax_info = self.get_tax_info(tax_percentage, tax_region, filtered_taxes)
                tax_code = tax_info["code"]
                tax_percentage_toc = tax_info["percentage"]
                tax_id = tax_info["id"]

                if tax_percentage == 0 and not global_exemption_reason:
                    if record.l10npt_vat_exempt_reason:
                        global_exemption_reason = record.l10npt_vat_exempt_reason.id
                    else:
                        raise UserError(_("The VAT rate is 0%, but no exemption reason was given."))

                lines.append({
                    "item_id": product_id,
                    "item_code": line.product_id.default_code,
                    "description": line.product_id.name,
                    "quantity": line.quantity,
                    "unit_price": line.price_unit,
                    "tax_code": tax_code,
                    "tax_percentage": tax_percentage_toc,
                    "tax_country_region": tax_region,
                    "item_type": "Product",
                    "exemption_reason": None,
                    "tax_id": tax_id
                })

            currency_obj = record.currency_id
            company_currency = record.company_id.currency_id
            date = record.invoice_date or fields.Date.today()
            conversion_rate = currency_obj._get_conversion_rate(currency_obj, company_currency, record.company_id, date)

            print("ytesttttt", record.name)

            payload = {
                "document_type": "FT",
                "status": 0,
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
                "vat_included_prices": record.journal_id.vat_included_prices if hasattr(record.journal_id,
                                                                                        'vat_included_prices') else False,
                "operation_country": tax_region,
                "currency_iso_code": record.currency_id.name,
                "currency_conversion_rate": conversion_rate,
                "apply_retention_when_paid": True,
                "notes": "Notas ao documento",
                "tax_exemption_reason_id": global_exemption_reason,
                "lines": lines,
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}"
            }

            response = requests.post(toc_endpoint, json=payload, headers=headers, timeout=120)

            if response.status_code != 200:
                raise UserError(
                    _(f"Error sending invoice {record.name} to TOConline. Status Code: {response.status_code}. Response body: {response.text}")
                )

            data = response.json()
            document_no = data.get('document_no', '')
            document_id = data.get('id', '')
            company_id_from_toconline = data.get('company_id')

            if company_id_from_toconline:
                self.env.company.toc_company_id = company_id_from_toconline

            record.write({
                'toc_status': 'sent',
                'toc_invoice_url': data.get('invoice_url', ''),
                'toc_document_no': document_no,
                'toc_document_id': document_id
            })

            self.env.cr.commit()

    def action_cancel_invoice_toconline(self):
        """
        Cancels the invoice in TOConline by setting its status to 4 (voided).Requires the user to input a reason.
        """
        for record in self:
            if not record.toc_document_id:
                raise UserError(_("This invoice was not sent to TOConline or is missing the TOConline document ID."))

            if record.toc_status != 'sent':
                raise UserError(_("Only invoices already sent to TOConline can be canceled."))

            reason = self.env.context.get('cancel_reason')
            if not reason:
                raise UserError(_("You must provide a reason to cancel the invoice."))

            access_token = self.env['toc.api'].get_access_token()
            if not access_token:
                raise UserError(_("Could not obtain access token for TOConline."))

            cancel_payload = {
                "data": {
                    "type": "commercial_sales_documents",
                    "id": str(record.toc_document_id),
                    "attributes": {
                        "status": 4,
                        "voided_reason": reason
                    }
                }
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}"
            }

            url = f"{TOC_BASE_URL}/api/commercial_sales_documents"
            response = requests.patch(url, json=cancel_payload, headers=headers)


            if response.status_code != 200:
                raise UserError(
                    _(f"Failed to cancel invoice on TOConline. Status: {response.status_code}, Response: {response.text}")
                )

            response_data = response.json()

            attributes = response_data.get('data', {}).get('attributes', {})
            reason = attributes.get('voided_reason', '')
            date = attributes.get('created_at', '')

            record.write({
                'status' : 'cancelled',
                'toc_status': 'cancelled',
                'cancellation_reason' : reason,
                'cancellation_date' : date
            })

            self.env.cr.commit()

    def get_customer_id(self, access_token, tax_number=None, email=None):
        """
            Search for a customer ID in TOConline by NIF or email.
        """

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
        customers = []
        if tax_number and tax_number.isdigit() and len(tax_number) == 9:
            search_url = f"{TOC_BASE_URL}/api/customers?filter[tax_registration_number]={tax_number}"
            response = requests.get(search_url, headers=headers)
            if response.status_code == 200:
                customers = response.json().get('data', [])
        if not customers and email:
            search_url = f"{TOC_BASE_URL}/api/customers?filter[email]={email}"
            response = requests.get(search_url, headers=headers)
            if response.status_code == 200:
                customers = response.json().get('data', [])
        if customers:
            print(_(f"Client found on TOConline: {customers[0]['attributes']['business_name']}"))
            return customers[0]["id"]
        return None


    def open_credit_note_wizard(self):
        self.ensure_one()

        return {
            'name': 'Send Credit Note',
            'type': 'ir.actions.act_window',
            'res_model': 'credit.note.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref('toc_invoice.view_credit_note_popup').id,
            'target': 'new',
            'context': {
                'default_invoice_id': self.id,
            }
        }

    def open_cancel_invoice_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'cancel.invoice.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_cancel_reason': '', 'active_id': self.id},
        }

import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
from odoo.addons.toc_invoice.utils import TOC_BASE_URL
_logger = logging.getLogger(__name__)
from odoo.exceptions import ValidationError
from datetime import date

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


    @api.constrains('invoice_line_ids')
    def _check_product_internal_reference(self):
        for record in self:
            for line in record.invoice_line_ids:
                product = line.product_id
                if product and not product.product_tmpl_id.default_code:
                    raise ValidationError(
                        f"The product '{product.name}' must have an internal reference (default_code) set."
                    )

    @api.constrains('invoice_date', 'invoice_date_due')
    def _check_invoice_dates(self):
        today = date.today()
        for record in self:
            if record.toc_status != 'sent' and record.toc_status != 'cancelled':
                if record.invoice_date and record.invoice_date < today:
                    raise ValidationError("The invoice date must be today or a future date.")
                if record.invoice_date_due and record.invoice_date_due < today:
                    raise ValidationError("The due date must be today or a future date.")
            if record.toc_status == 'cancelled':
                raise ValidationError("The invoice has already been cancelled in TOConline and cannot be modified.")

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
            return False

    def get_document_id_by_number(self, access_token, document_no):
        """
       Searches for a document by its number in TOConline and returns the corresponding ID.
        """

        response = self.env['toc.api'].toc_request(
            method='GET',
            url=f"{TOC_BASE_URL}/api/v1/commercial_sales_documents/",
            access_token=access_token
        )

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

        response =  self.env['toc.api'].toc_request(
            method='GET',
            url=f"{TOC_BASE_URL}/api/v1/commercial_sales_documents/",
            access_token=access_token
        )

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

        response =  self.env['toc.api'].toc_request(
            method='GET',
            url=f"{TOC_BASE_URL}/api/v1/commercial_sales_documents/",
            access_token=access_token
        )

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
        url = f"{TOC_BASE_URL}/api/taxes"
        response =  self.env['toc.api'].toc_request(
            method='GET',
            url=url,
            access_token=access_token
        )
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
        Verifica se o cliente já existe no TOConline pelo toc_online_id ou email (se NIF for 999999990 ou vazio).
        Caso não exista, cria-o.
        """

        if partner.toc_online_id:
            return partner.toc_online_id

        tax_number = partner.vat.replace(" ", "").strip() if partner.vat else "999999990"
        email = partner.email.strip() if partner.email else ""
        customers = []

        if tax_number != "999999990" and tax_number.isdigit() and len(tax_number) == 9:
            search_url = f"{TOC_BASE_URL}/api/customers?filter[tax_registration_number]={tax_number}"
            response = self.env['toc.api'].toc_request(
                method='GET',
                url=search_url,
                access_token=access_token
            )
            if response.status_code == 200:
                customers = response.json().get('data', [])
                if customers:
                    partner.sudo().write({'toc_online_id': customers[0]["id"]})
                    return customers[0]["id"]

        if email:
            search_url = f"{TOC_BASE_URL}/api/customers?filter[email]={email}"
            response = self.env['toc.api'].toc_request(
                method='GET',
                url=search_url,
                access_token=access_token
            )
            if response.status_code == 200:
                customers = response.json().get('data', [])
                if customers:
                    partner.sudo().write({'toc_online_id': customers[0]["id"]})
                    return customers[0]["id"]

        create_url = f"{TOC_BASE_URL}/api/customers"
        print("------ create_url:", create_url)
        customer_payload = {
            "data": {
                "type": "customers",
                "attributes": {
                    "tax_registration_number": tax_number,
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

        response = self.env['toc.api'].toc_request(
            method='POST',
            url=create_url,
            payload=customer_payload,
            access_token=access_token
        )

        if response.status_code in (200, 201):
            customer_id = response.json()["data"]["id"]
            partner.sudo().write({'toc_online_id': customer_id})
            return customer_id
        else:
            error_msg = response.text
            raise UserError(_("Error creating customer in TOConline: %s") % error_msg)

    def get_or_create_product_in_toconline(self, access_token, product):

        if not product.default_code:
            raise UserError(_("Product code (default_code) is empty."))

        search_url = f"{TOC_BASE_URL}/api/products?filter[item_code]={product.default_code}"
        response = self.env['toc.api'].toc_request(
            method='GET',
            url=search_url,
            access_token=access_token
        )

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

        response =  self.env['toc.api'].toc_request(
            method='POST',
            url=create_url,
            payload=product_payload,
            access_token=access_token
        )

        if response.status_code in (200, 201):
            data = response.json()
            product_id = data.get("data", {}).get("id")
            if not product_id:
                raise UserError(_(f"Product created, but ID was not returned: {data}"))
            return product_id
        else:
            raise UserError(_("Error creating product in TOConline: %s") % response.text)

    #################################  Overriding the action_post method to include integration with TOConline ###################################################################################################

    def action_post(self):
        res = super().action_post()
        for move in self:
            move.action_send_invoice_to_toconline()
            move._handle_credit_note_posting()
        return res

    def action_send_invoice_to_toconline(self):
        invoices_to_send = self.env['account.move'].search([
            ('state', '=', 'posted'),
            ('toc_status', '=', 'draft'),
            ('move_type', '=', 'out_invoice'),
        ])

        access_token = self.env['toc.api'].get_access_token()
        if not access_token:
            raise UserError(_("Could not get or refresh access token."))

        state_company = self.getStateCompany()
        tax_region = {
            "Madeira": "PT-MA",
            "Açores": "PT-AC",
            "Continente": "PT"
        }.get(state_company, "PT")

        taxes_data = self.get_taxes_from_toconline(access_token)
        filtered_taxes = [
            tax for tax in taxes_data
            if tax["attributes"]["tax_country_region"] == tax_region
        ]

        for record in invoices_to_send:
            with self.env.cr.savepoint():  # Savepoint por fatura
                try:
                    self._validate_partner_fields(record.partner_id, record)
                    customer_id = self.get_or_create_customer_in_toconline(access_token, record.partner_id)
                    lines, global_exemption_reason = self._build_lines(record, tax_region, filtered_taxes, access_token)
                    payload = self._build_payload(record, lines, global_exemption_reason, tax_region)

                    response =  self.env['toc.api'].toc_request(
                        method='POST',
                        url=f"{TOC_BASE_URL}/api/v1/commercial_sales_documents",
                        payload=payload,
                        access_token=access_token
                    )

                    self._handle_response(record, response)
                    for records in self:
                        if records.toc_status == 'sent':
                            records.checkbox = True

                except Exception as e:
                    _logger.exception("Error while sending invoice %s to TOConline: %s", record.name, str(e))
                    record.write({
                        'toc_status': 'error',
                        'toc_error_message': str(e),
                    })

    def _validate_partner_fields(self, partner, invoice):
        if not all([partner.name, partner.street, partner.city, partner.country_id, partner.zip]):
            raise UserError(_("Invoice %s customer is missing required fields.") % invoice.name)

    def _build_lines(self, record, tax_region, filtered_taxes, access_token):
        lines = []
        global_exemption_reason = None

        for line in record.invoice_line_ids:
            product_id = self.get_or_create_product_in_toconline(access_token, line.product_id)
            tax_percentage = line.tax_ids[0].amount if line.tax_ids else 0
            tax_info = self.get_tax_info(tax_percentage, tax_region, filtered_taxes)

            if tax_percentage == 0 and not global_exemption_reason:
                if record.l10npt_vat_exempt_reason:
                    global_exemption_reason = record.l10npt_vat_exempt_reason.id
                else:
                    raise UserError(_("0% VAT but no exemption reason."))

            lines.append({
                "item_id": product_id,
                "item_code": line.product_id.default_code,
                "description": line.product_id.name,
                "quantity": line.quantity,
                "unit_price": line.price_unit,
                "tax_code": tax_info["code"],
                "tax_percentage": tax_info["percentage"],
                "tax_country_region": tax_region,
                "item_type": "Product",
                "exemption_reason": None,
                "tax_id": tax_info["id"]
            })

        return lines, global_exemption_reason

    def _build_payload(self, record, lines, exemption_reason, tax_region):
        currency_obj = record.currency_id
        company_currency = record.company_id.currency_id
        date = record.invoice_date or fields.Date.today()

        return {
            "document_type": "FT",
            "status": 0,
            "date": date.strftime("%Y-%m-%d"),
            "finalize": 0,
            "customer_tax_registration_number": record.partner_id.vat.strip() if record.partner_id.vat else "Unknown",
            "customer_business_name": record.partner_id.name,
            "customer_address_detail": record.partner_id.street or "",
            "customer_postcode": record.partner_id.zip or "",
            "customer_city": record.partner_id.city or "",
            "customer_tax_country_region": tax_region,
            "customer_country": record.partner_id.country_id.code or "",
            "due_date": record.invoice_date_due.strftime("%Y-%m-%d") if record.invoice_date_due else "",
            "vat_included_prices": getattr(record.journal_id, 'vat_included_prices', False),
            "operation_country": tax_region,
            "currency_iso_code": currency_obj.name,
            "currency_conversion_rate": currency_obj._get_conversion_rate(currency_obj, company_currency,
                                                                          record.company_id, date),
            "apply_retention_when_paid": True,
            "notes": "Notes to the document",
            "tax_exemption_reason_id": exemption_reason,
            "lines": lines,
        }

    def _handle_response(self, record, response):
        if response.status_code != 200:
            error_msg = f"Invoice {record.name} failed: {response.status_code} - {response.text}"
            record.write({
                'toc_status': 'error',
                'toc_error_message': error_msg
            })
        else:
            data = response.json()
            record.write({
                'toc_status': 'sent',
                'toc_invoice_url': data.get('invoice_url', ''),
                'toc_document_no': data.get('document_no', ''),
                'toc_document_id': data.get('id', '')
            })

            toc_company_id = data.get('company_id')
            if toc_company_id:
                self.env.company.toc_company_id = toc_company_id

    ####################################################################################################################################

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
            try:
                url = f"{TOC_BASE_URL}/api/commercial_sales_documents"
                response = self.env['toc.api'].toc_request(
                    method='PATCH',
                    url=url,
                    payload=cancel_payload,
                    access_token=access_token
                )

            except Exception as e:
                for invoice in self:
                    if invoice.toc_status != 'cancelled':
                        invoice.state = "draft"
                        invoice.env.cr.commit()
                raise UserError(
                    _(f"{e}"))


            if response.status_code != 200:
                for invoice in self:
                    if invoice.toc_status != 'cancelled':
                        invoice.state = "draft"
                        invoice.env.cr.commit()
                raise UserError(
                    _(f"Failed to cancel invoice on TOConline. Status: {response.status_code}, Response: {response.text}")
                )
            response_data = response.json()

            attributes = response_data.get('data', {}).get('attributes', {})
            reason = attributes.get('voided_reason', '')
            date = attributes.get('created_at', '')

            record.write({
                'toc_status': 'cancelled',
                'cancellation_reason' : reason,
                'cancellation_date' : date
            })

            self.env.cr.commit()

    def get_customer_id(self, access_token, tax_number=None, email=None):
        """
            Search for a customer ID in TOConline by NIF or email.
        """
        customers = []
        if tax_number and tax_number.isdigit() and len(tax_number) == 9:
            search_url = f"{TOC_BASE_URL}/api/customers?filter[tax_registration_number]={tax_number}"
            response = self.env['toc.api'].toc_request(
                method='GET',
                url=search_url,
                access_token=access_token
            )
            if response.status_code == 200:
                customers = response.json().get('data', [])
        if not customers and email:
            search_url = f"{TOC_BASE_URL}/api/customers?filter[email]={email}"
            response = self.env['toc.api'].toc_request(
                method='GET',
                url=search_url,
                access_token=access_token
            )
            if response.status_code == 200:
                customers = response.json().get('data', [])
        if customers:
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

    def button_cancel(self):
        res = super().button_cancel()

        for invoice in self:
            access_token = self.env['toc.api'].get_access_token()
            if self._is_saft_exported(invoice.toc_document_id, access_token):
                raise ValidationError("It is not possible to cancel this document because it has already been included in the SAFT.")
            else:
                return invoice.open_cancel_invoice_wizard()

        return res


    def _is_saft_exported(self, document_id, access_token):
        url = f"{TOC_BASE_URL}/api/commercial_sales_documents/{document_id}"
        response = self.env['toc.api'].toc_request(
            method='GET',
            url=url,
            access_token=access_token
        )

        if response.status_code == 200:
            data = response.json().get("data", {}).get("attributes", {})
            communication_status = data.get("communication_status")
            return communication_status != "unsent"
        else:
            raise UserError(f"Error while checking SAFT status in TOConline: {response.text}")

    ### Credit Note ###

    def _handle_credit_note_posting(self):
        for move in self:
            if move.move_type == 'out_refund' and move.reversed_entry_id:
                move._send_credit_note_to_toconline()

    def _send_credit_note_to_toconline(self):
        self.ensure_one()

        exemption_reason= None

        if not self.reversed_entry_id or not self.reversed_entry_id.toc_document_no:
            raise UserError(_("The original invoice must have been sent to TOConline."))

        if self.toc_status_credit_note == 'sent':
            raise UserError(_("The credit note has already been sent to TOConline."))

        access_token = self.env['toc.api'].get_access_token()
        if not access_token:
            raise UserError(_("TOConline access token not found."))

        url_base = self.get_base_url()
        document_no = self.reversed_entry_id.toc_document_no

        document_data = self.env['credit.note.wizard'].get_document_lines(
            base_url=url_base,
            access_token=access_token,
            document_no=document_no,
        )

        tax_region = self.getStateCompany()
        region_map = {"Madeira": "PT-MA", "Açores": "PT-AC", "Continente": "PT"}
        tax_region = region_map.get(tax_region, "PT")

        taxes_data = self.get_taxes_from_toconline(access_token)
        filtered_taxes = [
            tax for tax in taxes_data
            if tax["attributes"]["tax_country_region"] == tax_region
        ]

        if not self.invoice_line_ids:
            raise UserError(_("No lines found on the credit note."))

        lines = []
        for line in self.invoice_line_ids:
            product = line.product_id
            quantity = line.quantity
            unit_price = line.price_unit
            tax_percentage = sum(line.tax_ids.mapped('amount'))
            tax_info = self.get_tax_info(tax_percentage, tax_region, filtered_taxes)
            tax_code = tax_info["code"]

            exemption_reason = None
            if tax_percentage == 0:
                exemption_reason = self.l10n_pt_vat_exempt_reason and self.l10n_pt_vat_exempt_reason.id
                if not exemption_reason:
                    raise UserError(_("VAT is 0% but no exemption reason provided."))

            lines.append({
                "item_id": None,
                "item_code": product.default_code,
                "description": line.name,
                "quantity": quantity,
                "unit_price": unit_price,
                "tax_code": tax_code,
                "tax_percentage": tax_percentage or 0.0,
                "tax_country_region": tax_region,
                "item_type": "Product",
                "exemption_reason": exemption_reason,
            })

        payload = {
            "document_type": "NC",
            "parent_document_reference": document_no,
            "date": self.invoice_date.strftime("%Y-%m-%d") if self.invoice_date else "",
            "due_date": self.invoice_date_due.strftime("%Y-%m-%d") if self.invoice_date_due else "",
            "customer_tax_registration_number": document_data.get("customer_tax_registration_number"),
            "customer_business_name": document_data.get("customer_business_name"),
            "customer_address_detail": document_data.get("customer_address_detail"),
            "customer_postcode": document_data.get("customer_postcode"),
            "customer_city": document_data.get("customer_city"),
            "customer_tax_country_region": tax_region,
            "customer_country": document_data.get("customer_country"),
            "payment_mechanism": "MO",
            "vat_included_prices": False,
            "operation_country": tax_region,
            "currency_iso_code": self.currency_id.name,
            "currency_conversion_rate": 1.0,
            "retention": 0,
            "retention_type": "IRS",
            "apply_retention_when_paid": False,
            "notes": f"Credit note relating to the invoice: {document_no}",
            "tax_exemption_reason_id": exemption_reason ,
            "lines": lines,
        }

        url = f"{url_base}/api/v1/commercial_sales_documents"
        response = self.env['toc.api'].toc_request(
            method='POST',
            url=url,
            payload=payload,
            access_token=access_token
        )

        if response.status_code != 200:
            raise UserError(_(f"Error sending credit note: {response.text}"))

        response_data = response.json()
        self.write({
            'toc_document_no_credit_note': response_data.get('document_no'),
            'toc_invoice_url': response_data.get('invoice_url', ''),
            'toc_status_credit_note': 'sent'
        })

        self._cr.commit()






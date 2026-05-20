import logging
import requests
import base64
from datetime import date

from markupsafe import Markup

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html2plaintext

from datetime import timedelta

_logger = logging.getLogger(__name__)


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

    toc_online_enabled = fields.Boolean(related='company_id.toc_online_enabled')


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
        toc_moves = self.filtered(lambda m: m.toc_online_enabled and m.journal_id.send_to_toconline)
        for record in toc_moves:
            product_lines = record.invoice_line_ids.filtered(
                lambda l: l.display_type == 'product' and not l.is_downpayment
            )
            for line in product_lines:
                product = line.product_id
                if product and not product.default_code:
                    raise ValidationError(
                        _("The product '%s' must have an internal reference (default_code) set.") % product.name
                    )

    @api.constrains('invoice_date', 'invoice_date_due')
    def _check_invoice_dates(self):
        today = date.today()
        toc_drafts = self.filtered(
            lambda m: m.toc_online_enabled
            and m.journal_id.send_to_toconline
            and m.state == 'draft'
            and m.toc_status not in ('sent', 'cancelled')
        )
        for record in toc_drafts:
            if record.invoice_date and record.invoice_date < today:
                raise ValidationError(_("The invoice date must be today or a future date."))
            if record.invoice_date_due and record.invoice_date_due < today:
                raise ValidationError(_("The due date must be today or a future date."))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.move_type != 'out_refund' or record.reversed_entry_id:
                continue
            if record.journal_id.send_to_toconline and record.toc_online_enabled:
                raise UserError(_(
                    "Credit notes must be created from an existing invoice when TOConline is "
                    "enabled. Please open the original invoice and use the 'Credit Note' action."
                ))
        return records

    @api.constrains('state')
    def _check_state_invoice(self):
        cancelled_in_toc = self.filtered(
            lambda m: m.toc_online_enabled and m.toc_status == 'cancelled' and m.state == 'draft'
        )
        if cancelled_in_toc:
            raise ValidationError(_("The invoice has already been cancelled in TOConline and cannot be modified."))

    def get_base_url(self):
        return (self.company_id or self.env.company)._get_toc_api_url()

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
            url=f"{self.company_id._get_toc_api_url()}/api/v1/commercial_sales_documents/",
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
            url=f"{self.company_id._get_toc_api_url()}/api/v1/commercial_sales_documents/",
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
            url=f"{self.company_id._get_toc_api_url()}/api/v1/commercial_sales_documents/",
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

    def get_taxes_from_toconline(self, access_token, company=None):
        """
            Search for available VAT rates on TOConline.
        """
        company = company or self.company_id or self.env.company
        url = f"{company._get_toc_api_url()}/api/taxes"
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
        conversion_rate = currency_obj.with_context(date=date)._convert(1, euro_currency, self.company_id or self.env.company, date)
        if conversion_rate <= 0:
            raise UserError(f"Unable to get conversion rate for{invoice_currency}.")
        return conversion_rate

    def get_or_create_customer_in_toconline(self, access_token, partner, company=None):
        """
        Verifica se o cliente já existe no TOConline pelo toc_online_id ou email (se NIF for 999999990 ou vazio).
        Caso não exista, cria-o.
        """
        company = company or self.company_id or self.env.company

        if partner.toc_online_id:
            return partner.toc_online_id

        tax_number = partner.vat.replace(" ", "").strip() if partner.vat else "999999990"
        if len(tax_number) > 2 and tax_number[:2].isalpha():
            tax_number = tax_number[2:]
        email = partner.email.strip() if partner.email else ""
        customers = []

        if tax_number != "999999990" and tax_number.isdigit() and len(tax_number) == 9:
            search_url = f"{company._get_toc_api_url()}/api/customers?filter[tax_registration_number]={tax_number}"
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
            search_url = f"{company._get_toc_api_url()}/api/customers?filter[email]={email}"
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

        create_url = f"{company._get_toc_api_url()}/api/customers"
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

    def get_or_create_product_in_toconline(self, access_token, product, company=None):
        company = company or self.company_id or self.env.company

        if not product.default_code:
            raise UserError(_("Product code (default_code) is empty."))

        search_url = f"{company._get_toc_api_url()}/api/products?filter[item_code]={product.default_code}"
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
        create_url = f"{company._get_toc_api_url()}/api/products"
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

    def action_post(self):
        toc_moves = self.filtered(
            lambda m: m.state == 'draft' and m.toc_online_enabled and m.journal_id.send_to_toconline
        )
        for move in toc_moves:
            access_token = self.env['toc.api'].get_access_token(company=move.company_id)
            move._adjust_date_for_chronology(access_token)

        res = super().action_post()
        posted_toc_moves = self.filtered(
            lambda m: m.toc_online_enabled and m.journal_id.send_to_toconline and m.invoice_date
        )
        for move in posted_toc_moves:
            previous_invoice = self.env['account.move'].search([
                ('move_type', '=', move.move_type),
                ('journal_id', '=', move.journal_id.id),
                ('company_id', '=', move.company_id.id),
                ('state', '=', 'draft'),
                ('invoice_date', '<', move.invoice_date),
            ], order='invoice_date asc', limit=1)

            if previous_invoice:
                ref = previous_invoice.name or previous_invoice.ref or str(previous_invoice.invoice_date)
                raise UserError(_(
                    "You cannot confirm this invoice because a previous invoice (%s) is still in draft."
                ) % ref)

            move.action_send_invoice_to_toconline()
            move._handle_credit_note_posting()
            if move.toc_status != 'sent' or move.checkbox != True:
                move.write({
                    'toc_status': 'error',
                })
                raise UserError(
                    _("It was not possible to send this invoice to TOConline. Please check the data and try again."))
        return res

    def action_send_invoice_to_toconline(self):

        if self:
            invoices_to_send = self
        else:
            invoices_to_send = self.env['account.move'].search([
                ('state', '=', 'posted'),
                ('toc_status', '=', 'draft'),
                ('move_type', '=', 'out_invoice'),
            ])

        if not invoices_to_send:
            return

        invoices_by_company = {}
        for inv in invoices_to_send.filtered(lambda m: m.toc_online_enabled and m.journal_id.send_to_toconline):
            invoices_by_company.setdefault(inv.company_id, self.env['account.move'])
            invoices_by_company[inv.company_id] |= inv

        for company, invoices in invoices_by_company.items():
            access_token = self.env['toc.api'].get_access_token(company=company)

            state_company = self.getStateCompany()
            tax_region = {
                "Madeira": "PT-MA",
                "Açores": "PT-AC",
                "Continente": "PT"
            }.get(state_company, "PT")

            taxes_data = self.get_taxes_from_toconline(access_token, company=company)
            filtered_taxes = [
                tax for tax in taxes_data
                if tax["attributes"]["tax_country_region"] == tax_region
            ]

            for record in invoices:
                with self.env.cr.savepoint():
                    self._validate_partner_fields(record.partner_id, record)
                    customer_id = self.get_or_create_customer_in_toconline(access_token, record.partner_id, company=company)
                    lines, global_exemption_reason = self._build_lines(record, tax_region, filtered_taxes, access_token)
                    payload = self._build_payload(record, lines, global_exemption_reason, tax_region)

                    response = self.env['toc.api'].toc_request(
                        method='POST',
                        url=f"{company._get_toc_api_url()}/api/v1/commercial_sales_documents",
                        payload=payload,
                        access_token=access_token
                    )

                    self._handle_response(record, response)
                    if record.toc_status == 'sent':
                        record.checkbox = True
                        response_data = response.json()
                        public_link = response_data.get("public_link")
                        if public_link:
                            msg = _(
                                "Invoice successfully sent to TOConline:<ul>"
                                "<li>Public link: <a href='{link}' target='_blank'>{link}</a></li>"
                                "</ul>"
                            ).format(link=public_link)

                            record.message_post(body=Markup(msg))

                        toc_document_id = response_data.get("id")
                        if toc_document_id:
                            self.download_and_attach_invoice_pdf(record, toc_document_id, access_token)

    def _validate_partner_fields(self, partner, invoice):
        missing_fields = []

        if not partner.name:
            missing_fields.append(_('Name'))
        if not partner.street:
            missing_fields.append(_('Street'))
        if not partner.city:
            missing_fields.append(_('City'))
        if not partner.country_id:
            missing_fields.append(_('Country'))
        if not partner.zip:
            missing_fields.append(_('ZIP Code'))

        if missing_fields:
            raise UserError(_(
                "Invoice %s customer is missing the following required field(s): %s"
            ) % (invoice.name, ", ".join(missing_fields)))

    def _build_lines(self, record, tax_region, filtered_taxes, access_token):
        lines = []
        global_exemption_reason = None

        for line in record.invoice_line_ids:
            product_id = self.get_or_create_product_in_toconline(access_token, line.product_id, company=record.company_id)
            tax_percentage = sum(t.amount for t in line.tax_ids) if line.tax_ids else 0
            tax_info = self.get_tax_info(tax_percentage, tax_region, filtered_taxes)

            if tax_percentage == 0 and not global_exemption_reason:
                if record.l10npt_vat_exempt_reason:
                    global_exemption_reason = record.l10npt_vat_exempt_reason.id
                else:
                    raise UserError(_("0% VAT but no exemption reason."))

            lines.append({
                "item_id": product_id,
                "item_code": line.product_id.default_code,
                "description": f"{line.name}" if line.name and line.name != line.product_id.name else line.product_id.name,
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

    def _get_last_toc_document_date(self, access_token):
        """ Consulta a TOConline para obter a data do último documento emitido """
        url = f"{self.company_id._get_toc_api_url()}/api/v1/commercial_sales_documents?sort=-date&page[size]=1"
        try:
            response = self.env['toc.api'].toc_request(
                method='GET',
                url=url,
                access_token=access_token
            )
            if response.status_code == 200:
                res_data = response.json()
                items = res_data if isinstance(res_data, list) else res_data.get('data', [])

                if items and len(items) > 0:
                    last_date_str = items[0].get('date')
                    _logger.info("Última data encontrada na TOConline: %s", last_date_str)
                    return fields.Date.from_string(last_date_str)
        except Exception as e:
            _logger.error("Falha ao validar cronologia TOConline: %s", str(e))
        return None

    def _adjust_date_for_chronology(self, access_token):
        self.ensure_one()
        last_toc_date = self._get_last_toc_document_date(access_token)

        if last_toc_date and self.invoice_date and self.invoice_date < last_toc_date:
            _logger.warning("Ajustando data da fatura %s por integridade cronológica.", self.name)

            days_diff = (self.invoice_date_due - self.invoice_date).days if self.invoice_date_due else 0

            if self.state == 'posted':
                self.with_context(check_move_validity=False).sudo().write({
                    'invoice_date': last_toc_date,
                    'invoice_date_due': last_toc_date + timedelta(days=days_diff)
                })
            else:
                self.write({
                    'invoice_date': last_toc_date,
                    'invoice_date_due': last_toc_date + timedelta(days=days_diff)
                })

            self.message_post(
                body=_("Data ajustada automaticamente para %s para cumprir a cronologia TOConline.") % last_toc_date)

    def _build_payload(self, record, lines, exemption_reason, tax_region):
        currency_obj = record.currency_id
        company_currency = record.company_id.currency_id

        invoice_date_to_send = record.invoice_date or fields.Date.today()

        due_date = record.invoice_date_due or invoice_date_to_send
        if due_date < invoice_date_to_send:
            due_date = invoice_date_to_send

        return {
            "document_type": "FT",
            "date": invoice_date_to_send.strftime("%Y-%m-%d"),
            "due_date": due_date.strftime("%Y-%m-%d"),
            "status": 0,
            "finalize": 0,
            "customer_tax_registration_number": record.partner_id.vat.strip() if record.partner_id.vat else "Unknown",
            "customer_business_name": record.partner_id.name,
            "customer_address_detail": record.partner_id.street or "",
            "customer_postcode": record.partner_id.zip or "",
            "customer_city": record.partner_id.city or "",
            "customer_tax_country_region": tax_region,
            "customer_country": record.partner_id.country_id.code or "",
            "vat_included_prices": getattr(record.journal_id, 'vat_included_prices', False),
            "operation_country": tax_region,
            "currency_iso_code": currency_obj.name,
            "currency_conversion_rate": currency_obj._get_conversion_rate(
                currency_obj, company_currency, record.company_id, invoice_date_to_send
            ),
            "apply_retention_when_paid": True,
            "notes": html2plaintext(record.narration or "")[:400],
            "tax_exemption_reason_id": exemption_reason,
            "lines": lines,
        }

    def _handle_response(self, record, response):
        if response.status_code != 200:
            error_msg = f"Invoice {record.name} failed: {response.status_code} - {response.text}"
            record.write({
                'toc_status': 'error',
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
                record.company_id.sudo().toc_company_id = toc_company_id

    def action_cancel_invoice_toconline(self):
        """
        Cancels the invoice in TOConline by setting its status to 4 (voided).Requires the user to input a reason.
        """
        for record in self:

            newer_invoice = self.env['account.move'].search([
                ('id', '>', record.id),
                ('move_type', '=', record.move_type),
                ('journal_id', '=', record.journal_id.id),
                ('company_id', '=', record.company_id.id),
                ('state', 'in', ['posted', 'cancel']),
            ], order='id asc', limit=1)

            if newer_invoice:
                raise UserError(_(
                    "You cannot cancel this invoice (%s) because a more recent invoice (%s) already exists and has been posted or cancelled."
                ) % (record.display_name, newer_invoice.display_name))

            if record.toc_online_enabled and record.journal_id.send_to_toconline:
                if not record.toc_document_id:
                    raise UserError(_("This invoice was not sent to TOConline or is missing the TOConline document ID."))

                if record.toc_status != 'sent':
                    raise UserError(_("Only invoices already sent to TOConline can be canceled."))

                reason = self.env.context.get('cancel_reason')
                if not reason:
                    raise UserError(_("You must provide a reason to cancel the invoice."))

                access_token = self.env['toc.api'].get_access_token(company=record.company_id)
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

                url = f"{record.company_id._get_toc_api_url()}/api/commercial_sales_documents"
                response = self.env['toc.api'].toc_request(
                        method='PATCH',
                        url=url,
                        payload=cancel_payload,
                        access_token=access_token
                    )


                if response.status_code != 200:
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
                    'cancellation_date' : date,
                    'state': 'cancel'
                })
                self.env.cr.commit()
                try:
                    response_data = response.json()
                    attributes = response_data.get('data', {}).get('attributes', {})
                    public_link = attributes.get("public_link")

                    if public_link:
                        msg = _(
                            "Invoice cancelled on TOConline:<ul>"
                            "<li>Public link: <a href='{link}' target='_blank'>{link}</a></li>"
                            "</ul>"
                        ).format(link=public_link)

                        record.message_post(body=Markup(msg))

                    toc_document_id = str(record.toc_document_id)
                    if toc_document_id:
                        self.download_and_attach_invoice_pdf(record, toc_document_id, access_token)

                except Exception as e:
                        raise UserError(_(
                            "The invoice was cancelled on TOConline, but the system was unable to post the confirmation message in the chatter. "
                            "Technical error: %s"
                        ) % str(e))
            else:
                record.state = 'cancel'

    def get_customer_id(self, access_token, tax_number=None, email=None, company=None):
        """
            Search for a customer ID in TOConline by NIF or email.
        """
        company = company or self.company_id or self.env.company
        customers = []
        if tax_number and tax_number.isdigit() and len(tax_number) == 9:
            search_url = f"{company._get_toc_api_url()}/api/customers?filter[tax_registration_number]={tax_number}"
            response = self.env['toc.api'].toc_request(
                method='GET',
                url=search_url,
                access_token=access_token
            )
            if response.status_code == 200:
                customers = response.json().get('data', [])
        if not customers and email:
            search_url = f"{company._get_toc_api_url()}/api/customers?filter[email]={email}"
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

    def _is_saft_exported(self, document_id, access_token, company=None):
        company = company or self.company_id or self.env.company
        url = f"{company._get_toc_api_url()}/api/commercial_sales_documents/{document_id}"
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
                if move.toc_online_enabled and move.journal_id.send_to_toconline:
                    move._send_credit_note_to_toconline()

    def _send_credit_note_to_toconline(self):
        self.ensure_one()

        if not self.toc_online_enabled:
            return

        exemption_reason= None

        if not self.reversed_entry_id or not self.reversed_entry_id.toc_document_no:
            raise UserError(_("The original invoice must have been sent to TOConline."))

        if self.toc_status_credit_note == 'sent':
            raise UserError(_("The credit note has already been sent to TOConline."))

        access_token = self.env['toc.api'].get_access_token(company=self.company_id)
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

        taxes_data = self.get_taxes_from_toconline(access_token, company=self.company_id)
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
                # exemption_reason = self.l10n_pt_vat_exempt_reason and self.l10n_pt_vat_exempt_reason.id
                exemption_reason = self.l10npt_vat_exempt_reason and self.l10npt_vat_exempt_reason.id
                if not exemption_reason:
                    raise UserError(_("VAT is 0% but no exemption reason provided."))



            lines.append({
                "item_id": None,
                "item_code": product.default_code,
                "description": f"{line.name}" if line.name and line.name != line.product_id.name else line.product_id.name,
                "quantity": quantity,
                "unit_price": unit_price,
                "tax_code": tax_code,
                "tax_percentage": tax_percentage or 0.0,
                "tax_country_region": tax_region,
                "item_type": "Product",
                "exemption_reason": exemption_reason,
            })

        global_exemption_reason = None

        zero_tax_line = self.invoice_line_ids.filtered(
            lambda l: any(round(t.amount, 2) == 0 for t in l.tax_ids)
        )[:1]

        if zero_tax_line:
                global_exemption_reason = self.l10npt_vat_exempt_reason and self.l10npt_vat_exempt_reason.id


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
            "tax_exemption_reason_id":  global_exemption_reason ,
            "lines": lines,
        }

        print('*' * 100)
        print(exemption_reason)
        print('*' * 100)

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

        for records in self:
            if records.toc_status == 'sent':
                response_data = response.json()
                public_link = response_data.get("public_link")
                if public_link:
                    msg = _(
                        "Invoice successfully sent to TOConline:<ul>"
                        "<li>Public link: <a href='{link}' target='_blank'>{link}</a></li>"
                        "</ul>"
                    ).format(link=public_link)

                    records.message_post(body=Markup(msg))
                toc_document_id = response_data.get("id")
                if toc_document_id:
                    self.download_and_attach_invoice_pdf(records, toc_document_id, access_token)

    def download_and_attach_invoice_pdf(self, record, toc_document_id, access_token):
        """
        Faz o download do PDF da fatura da TOConline e anexa ao registro da fatura no Odoo.
        """
        url_api = f"{record.company_id._get_toc_api_url()}/api/url_for_print/{toc_document_id}?filter[type]=Document&filter[copies]=1"


        response = self.env['toc.api'].toc_request(
            method='GET',
            url=url_api,
            access_token=access_token,
        )

        if response.status_code != 200:
            raise UserError(_("Failed to get PDF URL from TOConline."))

        try:
            url_data = response.json()["data"]["attributes"]["url"]
            pdf_url = f"{url_data['scheme']}://{url_data['host']}{url_data['path']}"
        except Exception as e:
            raise UserError(_("Error parsing PDF URL response: %s") % str(e))

        pdf_response = requests.get(pdf_url)
        if pdf_response.status_code != 200:
            raise UserError(_("Failed to download PDF from TOConline."))

        self.env['ir.attachment'].create({
            'name': f"Fatura_{record.name}.pdf",
            'res_model': 'account.move',
            'res_id': record.id,
            'type': 'binary',
            'datas': base64.b64encode(pdf_response.content),
            'mimetype': 'application/pdf',
        })

        record.message_post(body=Markup(
            _("PDF successfully downloaded and attached to the invoice.")
        ))

    def action_send_invoice_with_attachment(self):
        self.ensure_one()

        partner_email = self.partner_id.email
        if not partner_email:
            raise UserError(_("The customer does not have an email address."))

        template = self.env.ref('account.email_template_edi_invoice', raise_if_not_found=False)
        if not template:
            raise UserError(_("Invoice email template not found."))

        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', self.id),
        ], order='id desc', limit=1)

        mail_values = {
            'email_to': partner_email,
            'subject': f"{self.name} - Fatura",
            'body_html': template.body_html,
            'model': 'account.move',
            'res_id': self.id,
            'auto_delete': False,
        }

        if attachment:
            mail_values['attachment_ids'] = [(4, attachment.id)]
        else:
            mail_values['attachment_ids'] = []

        mail = self.env['mail.mail'].create(mail_values)
        mail.send()

        self.message_post(body=_("Invoice email successfully sent to the customer."))

    def action_invoice_sent(self):
        self.ensure_one()

        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', self.id),
        ], order='id desc', limit=1)

        report_action = super().action_invoice_sent()
        if attachment:
            report_action.setdefault('context', {})
            report_action['context'].update({
                'default_attachment_ids': [(6, 0, [attachment.id])],  # Limpa e adiciona só esse
            })

        return report_action

    def action_print_toc_or_standard(self):
        self.ensure_one()
        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', self.id),
        ], order='id desc', limit=1)

        if attachment:
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/{attachment.id}?download=true',
                'target': 'new',
            }
        else:
            return self.env.ref('account.account_invoices').report_action(self)








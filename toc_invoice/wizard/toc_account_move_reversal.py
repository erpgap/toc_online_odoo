from odoo import models, fields, api
from odoo.exceptions import UserError
import requests

class CreditNoteWizard(models.TransientModel):
    _name = 'credit.note.wizard'
    _description = 'Wizard para Envio de Nota de Crédito'

    invoice_id = fields.Many2one('account.move', string="Original Invoice", required=True)
    toc_document_no = fields.Char(string="TOConline Document Number", readonly=True)
    toc_document_no_credit_note = fields.Char(string="Credit Note Number", readonly=True)

    item_code = fields.Many2one('product.product', string="Product")
    description = fields.Char(string="Description")
    quantity = fields.Float(string="Amount", default=1.0)
    unit_price = fields.Float(string="Unit Price")
    tax_percentage = fields.Float(string="IVA (%)")
    tax_code = fields.Char(string="VAT code")

    total_value = fields.Float(string="Total Value")

    l10npt_vat_exempt_reason = fields.Many2one(
        'account.l10n_pt.vat.exempt.reason',
        string="VAT Exempt Reason",
        help="Reason for VAT exemption."
    )

    def get_total_value(self):
        return self.total_value


    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        invoice_id = self.env.context.get('active_id')

        if invoice_id:
            invoice = self.env['account.move'].browse(invoice_id)
            res.update({
                'invoice_id': invoice.id,
                'toc_document_no': invoice.toc_document_no,
            })

            if invoice.invoice_line_ids:
                first_line = invoice.invoice_line_ids.filtered(lambda l: l.product_id)[:1]
                if first_line:
                    line = first_line[0]
                    res.update({
                        'item_code': line.product_id.default_code or '',
                        'description': line.name or '',
                        'quantity': line.quantity,
                        'unit_price': line.price_unit,
                        'tax_percentage': sum(line.tax_ids.mapped('amount')) if line.tax_ids else 0.0,
                        'tax_code': ','.join(filter(None, line.tax_ids.mapped('description') or line.tax_ids.mapped('name')))
                    })

        return res

    def get_document_lines(self, base_url, access_token, document_no):
        """
        Gets the lines of a sales document from the TOConline API.

        :param base_url: TOConline API base URL
        :param access_token: Bearer authentication token
        :param document_no: Document number to be queried
        :return: List of document lines or None in case of error
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        url = f"{base_url}/api/v1/commercial_sales_documents?filter[document_no]={document_no}"

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, list) and len(data) > 0:
                data = data[0]

            if isinstance(data, dict):
                return data
            else:
                print("Error: API response does not contain a valid dictionary.")
                return None

        except requests.exceptions.RequestException as e:
            print(f"Error connecting to API: {e}")
            return None

    def get_document_lines_only(self, base_url, access_token, document_no):
        """
        Gets the lines of a sales document from the TOConline API.

        :param base_url: TOConline API base URL
        :param access_token: Bearer authentication token
        :param document_no: Document number to be queried
        :return: List of document lines or None in case of error
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        url = f"{base_url}/api/v1/commercial_sales_documents?filter[document_no]={document_no}"

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, list) and len(data) > 0:
                data = data[0]

            if isinstance(data, dict):
                return data.get("lines", [])
            else:
                print("Error: API response does not contain a valid dictionary.")
                return None

        except requests.exceptions.RequestException as e:
            print(f"Error connecting to API: {e}")
            return None

    @api.onchange('item_code')
    def _onchange_item_code(self):
        if self.item_code:
            product = self.item_code

            self.description = product.name or ''
            self.unit_price = product.list_price or 0.0
            self.tax_percentage = sum(product.taxes_id.mapped('amount')) if product.taxes_id else 0.0
            self.tax_code = ', '.join(
                filter(None, product.taxes_id.mapped('description') or product.taxes_id.mapped('name')))


    def action_confirm(self):
        self.ensure_one()

        if not self.invoice_id or not self.invoice_id.toc_document_no:
            raise UserError("The original invoice must have been sent to TOConline.")

        if self.env['account.move'].get_toc_status_credit_note() == 'sent':
            raise UserError("The credit note has already been sent to TOConline.")

        if not self.invoice_id.toc_status_credit_note:
            raise UserError("A credit note has already been created for this invoice.")

        access_token = self.env['toc.api'].get_access_token()
        if not access_token:
            raise UserError("TOConline access token not found.")

        url_base = self.invoice_id.get_base_url()
        invoice_toc_document_no = self.invoice_id.toc_document_no

        document_data = self.get_document_lines(url_base, access_token, invoice_toc_document_no)

        tax_region = self.invoice_id.getStateCompany()
        region_map = {"Madeira": "PT-MA", "Açores": "PT-AC", "Continente": "PT"}
        tax_region = region_map.get(tax_region, "PT")

        taxes_data = self.invoice_id.get_taxes_from_toconline(access_token)
        filtered_taxes = [
            tax for tax in taxes_data
            if tax["attributes"]["tax_country_region"] == tax_region
        ]

        tax_percentage = self.tax_percentage
        tax_info = self.invoice_id.get_tax_info(tax_percentage, tax_region, filtered_taxes)
        tax_code = tax_info["code"]

        global_exemption_reason = None

        if tax_percentage == 0 and not global_exemption_reason:
            if self.l10npt_vat_exempt_reason:
                global_exemption_reason = self.l10npt_vat_exempt_reason.id
            else:
                raise UserError("The VAT rate is 0%, but no exemption reason was given.")

        payload = {
            "document_type": "NC",
            "parent_document_reference": invoice_toc_document_no,
            "date": self.invoice_id.invoice_date.strftime("%Y-%m-%d") if self.invoice_id.invoice_date else "",
            "due_date": self.invoice_id.invoice_date_due.strftime(
                "%Y-%m-%d") if self.invoice_id.invoice_date_due else "",
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
            "currency_iso_code": self.invoice_id.currency_id.name,
            "currency_conversion_rate": 1.0,
            "retention": 0,
            "retention_type": "IRS",
            "apply_retention_when_paid": False,
            "notes": f"Credit note relating to the invoice: {invoice_toc_document_no}",
            "tax_exemption_reason_id": global_exemption_reason,
            "lines": [{
                "item_id": None,
                "item_code": self.item_code.default_code if self.item_code else '',
                "description": self.description or (self.item_code.name if self.item_code else ''),
                "quantity": self.quantity,
                "unit_price": self.unit_price,
                "tax_code": tax_code,
                "tax_percentage": tax_percentage or 0.0,
                "tax_country_region": tax_region,

                "item_type": "Product",
                "exemption_reason": global_exemption_reason,
            }],
        }

        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
        response = requests.post(f"{url_base}/api/v1/commercial_sales_documents", json=payload, headers=headers)

        variavel_auc = self.unit_price*self.quantity


        self.total_value = variavel_auc

        active_id = self.env.context.get('active_id')
        invoice = self.env['account.move'].browse(active_id)
        invoice.set_value_credit_note(variavel_auc)



        if response.status_code == 200:
            self.invoice_id.set_toc_status_credit_note('sent')
        if response.status_code != 200:
            raise UserError(f"Error sending credit note: {response.text}")

        response_data = response.json()

        reverse_vals = self.invoice_id._reverse_moves(default_values_list=[{
            'ref': f"Credit note generated from TOConline",
            'date': fields.Date.today(),
        }], cancel=False)

        credit_note = reverse_vals and reverse_vals[0]

        if credit_note.invoice_line_ids:
            line = credit_note.invoice_line_ids[0]
            tax = self.env['account.tax'].search([
                ('amount', '=', self.tax_percentage),
                ('type_tax_use', '=', 'sale'),
            ], limit=1)

            if not tax:
                raise UserError(
                    f"Tax with {self.tax_percentage}% not found in the system. Check tax configuration.")

            line.write({
                'product_id': self.item_code.id,
                'name': self.description,
                'quantity': self.quantity ,
                'price_unit': self.unit_price,
                'tax_ids': [(6, 0, tax.ids)],
            })

        if not credit_note:
            raise UserError("Error creating credit note in Odoo.")


        credit_note.write({
            'toc_document_no_credit_note': response_data.get('document_no'),
            'toc_invoice_url': response_data.get('invoice_url', ''),
        })

        credit_note._cr.commit()



        return {'type': 'ir.actions.act_window_close'}



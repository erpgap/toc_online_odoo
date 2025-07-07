from odoo import models, api, fields, _
from odoo.exceptions import UserError
import logging
from odoo.addons.toc_invoice.utils import TOC_BASE_URL
import requests

_logger = logging.getLogger(__name__)


class InvoiceSync(models.Model):
    _name = 'invoice.sync'
    _description = 'Sync Invoices from TOConline'

    @api.model
    def sync_credit_notes_from_toc(self):
        """Fetch credit notes from TOConline, check which are missing in Odoo, and create them."""

        companies = self.env['res.company'].search([('toc_company_id', '!=', False)])
        for company in companies:
            access_token = self.env['toc.api'].get_access_token(company=company)
            if not access_token:
                continue

            url = f"{TOC_BASE_URL}/api/v1/commercial_sales_documents?filter[document_type]=NC&sort=-date"

            try:
                response = self.env['toc.api'].toc_request(
                    method='GET',
                    url=url,
                    access_token=access_token,
                )

                documents = response.json()

                if not isinstance(documents, list):
                    raise UserError(_("Unexpected TOConline response format."))

                toc_nc_docs = [
                    doc for doc in documents
                    if doc.get("document_type") == "NC"
                       and doc.get("document_no")
                       and doc.get("date")
                ]

                toc_doc_nos = [doc.get("document_no") for doc in toc_nc_docs]

                existing_credit_notes = self.env['account.move'].search([
                    ('move_type', '=', 'out_refund'),
                    ('toc_document_no_credit_note', 'in', toc_doc_nos)
                ])
                existing_toc_nos = set(existing_credit_notes.mapped('toc_document_no_credit_note'))

                new_toc_docs = [doc for doc in toc_nc_docs if doc.get("document_no") not in existing_toc_nos]

                for doc in new_toc_docs:
                    try:
                        self.create_credit_note_in_odoo(doc)
                    except Exception as e:
                        _logger.error("Error creating credit note %s: %s", doc.get("document_no"), str(e))

                _logger.info("Successfully created %d new credit notes from TOConline for company %s.",
                             len(new_toc_docs), company.name)

            except Exception as e:
                _logger.error("Error during credit note sync for company %s: %s", company.name, str(e), exc_info=True)
                raise UserError(_(f"Error: {str(e)}"))

    def create_invoice_in_odoo(self, toc_document_data, company):
        toc_document_id = toc_document_data.get('id')
        document_no = toc_document_data.get('document_no')
        status = toc_document_data.get('status')
        tax_reason = toc_document_data.get('tax_exemption_reason_id')

        lines = toc_document_data.get('lines', [])
        if not lines:
            raise UserError(f"Invoice {document_no} don't have lines")

        line = lines[0]
        quantity = line.get("quantity")
        unit_price = line.get("unit_price")
        tax_percentage = line.get("tax_percentage")
        codeP = line.get("item_code")

        toc_document = self._get_toc_document_by_id(toc_document_id, company)
        if not toc_document:
            raise UserError(f"Invoice {document_no} not found in TOConline.")

        toc_client_id = toc_document.get('customer_id')
        partner = self.env['res.partner'].search([('toc_online_id', '=', toc_client_id)], limit=1)
        if not partner:
            partner_vals = {
                'name': toc_document.get('customer_business_name') or 'Cliente TOC',
                'toc_online_id': toc_client_id,
                'street': toc_document.get('customer_address_detail'),
                'zip': toc_document.get('customer_postcode'),
                'city': toc_document.get('customer_city'),
                'vat': toc_document.get('customer_tax_registration_number'),
                'country_id': self.env['res.country'].search(
                    [('code', '=', toc_document.get('customer_country', 'PT'))], limit=1).id,

                'customer_rank': 1,
            }
            partner = self.env['res.partner'].create(partner_vals)
            _logger.info("Criado cliente novo a partir da fatura TOC %s com ID %s", document_no, toc_client_id)

        self = self.with_company(company).sudo()

        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('company_id', '=', company.id)
        ], limit=1)
        if not journal:
            raise UserError(f"No sales journals found for the company{company.name}.")

        tax_percentage_float = float(tax_percentage)

        tax = self.env['account.tax'].search([
            ('amount', '>=', tax_percentage_float - 0.01),
            ('amount', '<=', tax_percentage_float + 0.01),
            ('type_tax_use', '=', 'sale'),
            ('company_id', '=', company.id),
            '|',
            ('country_id', '=', False),
            ('country_id', '=', company.country_id.id)
        ], limit=1)

        tax_ids_for_line = []
        if not tax:
            state_company = company.state_id.name if company.state_id else ""
            region_map = {
                "Madeira": "PT-MA",
                "Açores": "PT-AC",
                "Continente": "PT"
            }
            tax_region = region_map.get(state_company, "PT")

            taxes_data = self.env['account.move'].get_taxes_from_toconline(
                self.env['toc.api'].get_access_token(company=company))
            valid_region_taxes = [
                t for t in taxes_data
                if t["attributes"]["tax_country_region"] == tax_region
            ]

            found_valid_tax = any(
                abs(float(t["attributes"]["tax_percentage"]) - tax_percentage_float) < 0.01
                for t in valid_region_taxes
            )

            if not found_valid_tax:
                raise UserError(
                    f"The invoice {document_no} has a VAT rate {tax_percentage}% which is not valid for the region{tax_region}."
                )

            if not tax_reason and tax_percentage_float == 0:
                raise UserError(
                    f"The invoice {document_no} has 0% VAT but no exemption reason was provided."
                )

        else:
            tax_ids_for_line = [(6, 0, [tax.id])]

        product = self.env['product.product'].search([('default_code', '=', codeP)], limit=1)
        if not product:
            product_vals = {
                'name': line.get('description') or 'Produto TOC',
                'default_code': codeP,
                'list_price': unit_price,
                'taxes_id': tax_ids_for_line,
                'company_id': company.id,
            }
            product = self.env['product.product'].create(product_vals)
            _logger.info("Criado novo produto a partir da fatura TOC %s: código %s", document_no, codeP)

        invoice_line_vals = {
            'product_id': product.id,
            'name': line.get('description'),
            'quantity': quantity,
            'price_unit': unit_price,
            'tax_ids': tax_ids_for_line,
        }

        toc_status_finalized = None
        if status == 1:
            toc_status_finalized = 'sent'
        elif status == 4:
            toc_status_finalized = 'cancelled'

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': toc_document_data.get('date'),
            'invoice_date_due': toc_document_data.get('due_date'),
            'company_id': company.id,
            'journal_id': journal.id,
            'l10npt_vat_exempt_reason': tax_reason,
            'invoice_line_ids': [(0, 0, invoice_line_vals)],
            'toc_document_no': document_no,
            'toc_status': toc_status_finalized,
            'toc_document_id': toc_document_id
        }

        invoice = self.env['account.move'].create(invoice_vals)
        invoice.action_post()
        self.env.cr.commit()

        _logger.info("Invoice vals para %s: %s", document_no, invoice_vals)

        return invoice

    def _get_toc_document_by_id(self, toc_document_id, company):
        access_token = self.env['toc.api'].get_access_token(company=company)
        if not access_token:
            raise UserError(f"TOConline access token not found for company {company.name}.")

        url = f"{TOC_BASE_URL}/api/v1/commercial_sales_documents/{toc_document_id}"

        try:
            response = self.env['toc.api'].toc_request(
                method='GET',
                url=url,
                access_token=access_token,
            )
            return response.json()
        except Exception as e:
            _logger.error(f"Error connecting to TOConline for document ID {toc_document_id}: {str(e)}")
            return None



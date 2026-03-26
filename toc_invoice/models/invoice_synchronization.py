import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .toc_online_service import TocOnlineService

_logger = logging.getLogger(__name__)


class InvoiceSync(models.AbstractModel):
    _name = 'invoice.sync'
    _description = 'Sync Invoices from TOConline'

    def create_invoice_in_odoo(self, toc_document_data, company):
        """
        Professional synchronization of TOConline invoices into Odoo.
        Handles date chronology issues and prevents duplicate records.
        """
        toc_document_id = toc_document_data.get('id')
        document_no = toc_document_data.get('document_no')
        status = toc_document_data.get('status')
        tax_reason = toc_document_data.get('tax_exemption_reason_id')

        # --- 1. PREVENT DUPLICATES ---
        existing_invoice = self.env['account.move'].sudo().search([
            ('toc_document_no', '=', document_no),
            ('company_id', '=', company.id)
        ], limit=1)

        if existing_invoice:
            _logger.info("Invoice %s already exists in Odoo. Skipping creation.", document_no)
            return existing_invoice

        lines = toc_document_data.get('lines', [])
        if not lines:
            raise UserError(_("Invoice %s has no lines.") % document_no)

        line = lines[0]
        quantity = line.get("quantity")
        unit_price = line.get("unit_price")
        tax_percentage = line.get("tax_percentage")
        codeP = line.get("item_code")

        # Fetch full document details from TOC
        service = TocOnlineService(company, self.env)
        toc_document = service.get_document_by_id(toc_document_id)
        if not toc_document:
            raise UserError(_("Invoice %s not found in TOConline.") % document_no)

        # --- 2. PARTNER HANDLING ---
        toc_client_id = toc_document.get('customer_id')
        partner = self.env['res.partner'].with_company(company).search(
            [('toc_online_id', '=', toc_client_id)], limit=1,
        )
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
            partner = self.env['res.partner'].with_company(company).sudo().create(partner_vals)
            _logger.info("New partner created from TOC invoice %s: %s", document_no, toc_client_id)

        # Switch context to company and sudo for record creation
        self = self.with_company(company).sudo()

        # --- 3. TAX & JOURNAL HANDLING ---
        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('company_id', '=', company.id)
        ], limit=1)
        if not journal:
            raise UserError(_("No sales journal found for company %s.") % company.name)

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
            # Fallback for regional taxes (Madeira/Azores)
            state_company = company.state_id.name if company.state_id else ""
            tax_region = TocOnlineService.get_tax_region(state_company)

            # Validate against TOC allowed taxes
            taxes_data = service.get_taxes()

            valid_region_taxes = [
                t for t in taxes_data
                if t["attributes"]["tax_country_region"] == tax_region
            ]

            found_valid_tax = any(
                abs(float(t["attributes"]["tax_percentage"]) - tax_percentage_float) < 0.01
                for t in valid_region_taxes
            )

            if not found_valid_tax:
                raise UserError(_("VAT rate %s%% is invalid for region %s.") % (tax_percentage, tax_region))

            if not tax_reason and tax_percentage_float == 0:
                raise UserError(
                    _("0%% VAT detected for invoice %s but no exemption reason was provided.") % document_no)
        else:
            tax_ids_for_line = [(6, 0, [tax.id])]

        # --- 4. PRODUCT HANDLING ---
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
            _logger.info("New product created from TOC invoice %s: %s", document_no, codeP)

        # --- 5. DATE & CHRONOLOGY FIX ---
        invoice_date_raw = toc_document_data.get('date')
        due_date_raw = toc_document_data.get('due_date')

        today = fields.Date.today()
        invoice_date = fields.Date.from_string(invoice_date_raw) if invoice_date_raw else today
        due_date = fields.Date.from_string(due_date_raw) if due_date_raw else today

        if invoice_date < today:
            _logger.warning(
                "Invoice %s has backdated date (%s). Adjusting to today (%s) to avoid chronology error.",
                document_no, invoice_date, today)
            invoice_date = today

        if due_date < invoice_date:
            due_date = invoice_date

        # --- 6. INVOICE CREATION ---
        toc_status_finalized = 'draft'
        if status == 1:
            toc_status_finalized = 'sent'
        elif status == 4:
            toc_status_finalized = 'cancelled'

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': invoice_date,
            'invoice_date_due': due_date,
            'company_id': company.id,
            'journal_id': journal.id,
            'l10npt_vat_exempt_reason': tax_reason,
            'invoice_line_ids': [(0, 0, {
                'product_id': product.id,
                'name': line.get('description'),
                'quantity': quantity,
                'price_unit': unit_price,
                'tax_ids': tax_ids_for_line,
            })],
            'toc_document_no': document_no,
            'toc_status': toc_status_finalized,
            'toc_document_id': toc_document_id
        }

        invoice = self.env['account.move'].create(invoice_vals)

        try:
            invoice.action_post()
            self.env.cr.commit()
            _logger.info("Invoice %s successfully synchronized and posted.", document_no)
        except Exception as e:
            _logger.error("Error posting synchronized invoice %s: %s", document_no, str(e))

        return invoice

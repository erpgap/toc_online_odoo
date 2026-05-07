import logging
from datetime import date

from markupsafe import Markup

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html2plaintext

from datetime import timedelta

from .toc_online_service import TocOnlineService

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
    ], string="TOConline Credit Note Status", default='draft')


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

    def get_value_credit_note(self):
        return self.credit_note_total_value

    @api.depends('toc_document_no', 'toc_document_no_credit_note', 'move_type', 'name')
    def _compute_toc_display_number(self):
        for move in self:
            if move.move_type in ('out_refund', 'in_refund'):
                move.toc_display_number = move.toc_document_no_credit_note or move.name or '/'
            else:
                move.toc_display_number = move.toc_document_no or move.name or '/'

    @api.depends('amount_total_in_currency_signed', 'credit_note_total_value', 'move_type')
    def _compute_toc_total_display(self):
        for move in self:
            if move.move_type in ('out_refund', 'in_refund'):
                move.toc_total_display = -abs(move.credit_note_total_value)
            else:
                move.toc_total_display = move.amount_total_in_currency_signed


    def _compute_is_l10npt_vat_enabled(self):
        for invoice in self:
            invoice.is_l10npt_vat_enabled = (
                invoice.country_code == "PT"
                and invoice.is_sale_document()
                and invoice.company_id.toc_online_enabled
            )

    @api.constrains('invoice_line_ids')
    def _check_product_internal_reference(self):
        for record in self:
            if not (record.company_id.toc_online_enabled and record.journal_id.send_to_toconline):
                continue
            for line in record.invoice_line_ids.filtered(lambda l: l.display_type == 'product' and not l.is_downpayment):
                product = line.product_id
                if product and not product.default_code:
                    raise ValidationError(
                        _("The product '%s' must have an internal reference (default_code) set.") % product.name
                    )

    @api.constrains('invoice_date', 'invoice_date_due')
    def _check_invoice_dates(self):
        today = date.today()
        for record in self:
            if not (record.company_id.toc_online_enabled and record.journal_id.send_to_toconline) or record.state != 'draft':
                continue
            if record.toc_status not in ('sent', 'cancelled'):
                if record.invoice_date and record.invoice_date < today:
                    raise ValidationError(_("The invoice date must be today or a future date."))
                if record.invoice_date_due and record.invoice_date_due < today:
                    raise ValidationError(_("The due date must be today or a future date."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('move_type') != 'out_refund' or vals.get('reversed_entry_id'):
                continue
            company = self.env['res.company'].browse(
                vals.get('company_id') or self.env.company.id
            )
            if company.toc_online_enabled:
                raise UserError(_(
                    "Credit notes must be created from an existing invoice when TOConline is "
                    "enabled. Please open the original invoice and use the 'Credit Note' action."
                ))
        return super().create(vals_list)

    def get_toc_status_credit_note(self):
        return  self.toc_status_credit_note

    def set_toc_status_credit_note(self , teste):
        self.toc_status_credit_note = teste

    def get_ID_invoice(self):
        self.ensure_one()
        return self.toc_document_no

    def _get_company_tax_region(self):
        company = self.company_id or self.env.company
        state_name = company.partner_id.state_id.name if company.partner_id.state_id else ""
        return TocOnlineService.get_tax_region(state_name)

    def get_conversion_rate_to_euro(self, invoice_currency):
        if invoice_currency == 'EUR':
            return 1

        currency_obj = self.env['res.currency'].search([('name', '=', invoice_currency)], limit=1)
        euro_currency = self.env['res.currency'].search([('name', '=', 'EUR')], limit=1)
        if not currency_obj or not euro_currency:
            raise UserError(_("The currency %s or EUR was not found in Odoo.") % invoice_currency)

        if self.state == "posted":
            if self.invoice_currency_rate:
                return self.invoice_currency_rate
            else:
                raise UserError(
                    _("No exchange rates found for %s. Check settings.") % invoice_currency
                )

        invoice_date = self.invoice_date or fields.Date.today()
        company = self.company_id or self.env.company
        conversion_rate = currency_obj.with_context(date=invoice_date)._convert(
            1, euro_currency, company, invoice_date,
        )
        if conversion_rate <= 0:
            raise UserError(_("Unable to get conversion rate for %s.") % invoice_currency)
        return conversion_rate

    def action_post(self):
        toc_moves = self.filtered(
            lambda m: m.state == 'draft' and m.company_id.toc_online_enabled and m.journal_id.send_to_toconline
        )
        for move in toc_moves:
            service = TocOnlineService(move.company_id, self.env)
            move._adjust_date_for_chronology(service)

        res = super().action_post()
        for move in self:
            if not (move.company_id.toc_online_enabled and move.journal_id.send_to_toconline):
                continue
            if not move.invoice_date:
                continue
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

            if move.company_id.toc_online_enabled and move.journal_id.send_to_toconline:
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

        # Group by company for multi-company support
        invoices_by_company = {}
        for inv in invoices_to_send:
            invoices_by_company.setdefault(inv.company_id, self.env['account.move'])
            invoices_by_company[inv.company_id] |= inv

        for company, invoices in invoices_by_company.items():
            service = TocOnlineService(company, self.env)

            tax_region = TocOnlineService.get_tax_region(
                company.partner_id.state_id.name if company.partner_id.state_id else ""
            )

            taxes_data = service.get_taxes()
            filtered_taxes = [
                tax for tax in taxes_data
                if tax["attributes"]["tax_country_region"] == tax_region
            ]

            for record in invoices:
                with self.env.cr.savepoint():
                    self._validate_partner_fields(record.partner_id, record)
                    service.get_or_create_customer(record.partner_id)
                    lines, global_exemption_reason = self._build_lines(
                        record, tax_region, filtered_taxes, service,
                    )
                    payload = self._build_payload(record, lines, global_exemption_reason, tax_region)

                    response = service.send_document(payload)

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
                            service.download_and_attach_pdf(
                                record, toc_document_id, f"Fatura_{record.name}.pdf",
                                message=_("PDF successfully downloaded and attached to the invoice."),
                            )

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

    def _build_lines(self, record, tax_region, filtered_taxes, service):
        lines = []
        global_exemption_reason = None

        for line in record.invoice_line_ids.filtered(lambda rec: rec.display_type == 'product' and not rec.is_downpayment):
            product_id = service.get_or_create_product(line.product_id)
            tax_percentage = sum(t.amount for t in line.tax_ids) if line.tax_ids else 0
            tax_info = service.get_tax_info(tax_percentage, tax_region, filtered_taxes)

            if tax_percentage == 0 and not global_exemption_reason:
                if record.l10npt_vat_exempt_reason:
                    exemption_code = record.l10npt_vat_exempt_reason.code
                    global_exemption_reason = service.get_tax_exemption_reason_id(exemption_code)
                    if not global_exemption_reason:
                        raise UserError(
                            _("Exemption reason '%s' not found in TOConline.") % exemption_code
                        )
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

    def _get_toc_document_type(self):
        """Map Odoo move_type to TOConline document_type code."""
        self.ensure_one()
        return "NC" if self.move_type == "out_refund" else "FT"

    def _get_last_toc_document_date(self, service):
        return service.get_last_document_date(document_type=self._get_toc_document_type())

    def _adjust_date_for_chronology(self, service):
        self.ensure_one()
        last_toc_date = service.get_last_document_date(
            document_type=self._get_toc_document_type(),
        )

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
                record.company_id.toc_company_id = toc_company_id

    def action_cancel_invoice_toconline(self):
        for record in self:
            if not record.journal_id.send_to_toconline:
                record.button_cancel()
                continue

            if not record.toc_document_id:
                raise UserError(_("This invoice was not sent to TOConline or is missing the TOConline document ID."))

            service = TocOnlineService(record.company_id, self.env)

            toc_doc = service.get_document_by_id(record.toc_document_id)
            toc_current_status = (toc_doc or {}).get('status')

            if toc_doc and toc_current_status == 4:
                voided_reason = toc_doc.get('voided_reason', '')
                cancel_date = toc_doc.get('created_at', '')
                record.write({
                    'toc_status': 'cancelled',
                    'cancellation_reason': voided_reason or record.cancellation_reason,
                    'cancellation_date': cancel_date or fields.Date.context_today(record),
                })
                msg = _("Invoice was already cancelled on TOConline. Synced cancellation details from TOConline.")
                if voided_reason:
                    msg += _("<br/>Reason: %s") % voided_reason
                record.message_post(body=Markup(msg))
                record.button_cancel()
                continue

            reason = self.env.context.get('cancel_reason')
            if not reason:
                raise UserError(_("You must provide a reason to cancel the invoice."))

            response = service.cancel_document(record.toc_document_id, reason)

            if response.status_code != 200:
                raise UserError(
                    _("Failed to cancel invoice on TOConline. Status: %s, Response: %s")
                    % (response.status_code, response.text)
                )
            response_data = response.json()

            attributes = response_data.get('data', {}).get('attributes', {})
            cancel_reason = attributes.get('voided_reason', '')
            cancel_date = attributes.get('created_at', '')

            record.write({
                'toc_status': 'cancelled',
                'cancellation_reason': cancel_reason,
                'cancellation_date': cancel_date,
            })
            record.button_cancel()
            try:
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
                    service.download_and_attach_pdf(
                        record, toc_document_id, f"Fatura_{record.name}.pdf",
                        message=_("PDF successfully downloaded and attached to the invoice."),
                    )

            except Exception as e:
                    raise UserError(_(
                        "The invoice was cancelled on TOConline, but the system was unable to post the confirmation message in the chatter. "
                        "Technical error: %s"
                    ) % str(e))

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
        self.ensure_one()
        if self.journal_id.send_to_toconline and self.toc_document_id:
            service = TocOnlineService(self.company_id, self.env)
            toc_doc = service.get_document_by_id(self.toc_document_id)
            toc_attributes = (toc_doc or {}).get('data', {}).get('attributes', {})
            if toc_attributes.get('status') == 4:
                self.action_cancel_invoice_toconline()
                return {'type': 'ir.actions.act_window_close'}

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'cancel.invoice.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_cancel_reason': '', 'active_id': self.id},
        }

    def open_toc_link_invoice_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Link TOConline Invoice"),
            'res_model': 'toc.link.invoice.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_invoice_id': self.id},
        }

    ### Credit Note ###

    def _handle_credit_note_posting(self):
        for move in self:
            if move.move_type == 'out_refund' and move.reversed_entry_id:
                if move.journal_id.send_to_toconline:
                    move._send_credit_note_to_toconline()

    def _send_credit_note_to_toconline(self):
        self.ensure_one()

        exemption_reason = None

        if not self.reversed_entry_id or not self.reversed_entry_id.toc_document_no:
            raise UserError(_("The original invoice must have been sent to TOConline."))

        if self.toc_status_credit_note == 'sent':
            raise UserError(_("The credit note has already been sent to TOConline."))

        service = TocOnlineService(self.company_id, self.env)

        document_no = self.reversed_entry_id.toc_document_no
        document_data = service.get_document_lines(document_no)

        tax_region = self._get_company_tax_region()

        taxes_data = service.get_taxes()
        filtered_taxes = [
            tax for tax in taxes_data
            if tax["attributes"]["tax_country_region"] == tax_region
        ]

        if not self.invoice_line_ids:
            raise UserError(_("No lines found on the credit note."))

        lines = []
        for line in self.invoice_line_ids.filtered(lambda l: l.display_type == 'product' and not l.is_downpayment):
            product = line.product_id
            quantity = line.quantity
            unit_price = line.price_unit
            tax_percentage = sum(line.tax_ids.mapped('amount'))
            tax_info = service.get_tax_info(tax_percentage, tax_region, filtered_taxes)
            tax_code = tax_info["code"]

            exemption_reason = None
            if tax_percentage == 0:
                if self.l10npt_vat_exempt_reason:
                    exemption_code = self.l10npt_vat_exempt_reason.code
                    exemption_reason = service.get_tax_exemption_reason_id(exemption_code)
                    if not exemption_reason:
                        raise UserError(
                            _("Exemption reason '%s' not found in TOConline.") % exemption_code
                        )
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
            lambda l: l.display_type == 'product' and not l.is_downpayment and any(round(t.amount, 2) == 0 for t in l.tax_ids)
        )[:1]

        if zero_tax_line and self.l10npt_vat_exempt_reason:
            exemption_code = self.l10npt_vat_exempt_reason.code
            global_exemption_reason = service.get_tax_exemption_reason_id(exemption_code)
            if not global_exemption_reason:
                raise UserError(
                    _("Exemption reason '%s' not found in TOConline.") % exemption_code
                )


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

        response = service.send_document(payload)

        if response.status_code != 200:
            raise UserError(_("Error sending credit note: %s") % response.text)

        response_data = response.json()
        self.write({
            'toc_document_no_credit_note': response_data.get('document_no'),
            'toc_invoice_url': response_data.get('invoice_url', ''),
            'toc_status_credit_note': 'sent'
        })

        self.env.cr.commit()

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
                    service.download_and_attach_pdf(
                        records, toc_document_id, f"Fatura_{records.name}.pdf",
                        message=_("PDF successfully downloaded and attached to the invoice."),
                    )

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
                'default_attachment_ids': [(6, 0, [attachment.id])],
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

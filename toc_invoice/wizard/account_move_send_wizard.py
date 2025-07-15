from odoo import models, api

class AccountMoveSendWizard(models.TransientModel):
    _inherit = 'account.move.send.wizard'

    def action_send_and_print(self, allow_fallback_pdf=False):
        self.ensure_one()

        if self.alerts:
            self._raise_danger_alerts(self.alerts)

        self._update_preferred_settings()

        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', self.move_id.id),
        ], order='id desc', limit=1)

        if not attachment:
            result = super().action_send_and_print(allow_fallback_pdf=allow_fallback_pdf)
            return result

        attachments = [attachment.id]

        if self.sending_methods and 'manual' in self.sending_methods:
            return self._action_download(attachments)
        else:
            template = self.mail_template_id or self.move_id._get_default_mail_template()
            mail_id = template.with_context(attachment_ids=attachments).send_mail(self.move_id.id, force_send=False)
            mail = self.env['mail.mail'].browse(mail_id)
            mail.attachment_ids = [(6, 0, attachments)]
            mail.send()

            return {'type': 'ir.actions.act_window_close'}

    @api.depends('mail_template_id', 'sending_methods', 'invoice_edi_format', 'extra_edis')
    def _compute_mail_attachments_widget(self):
        for wizard in self:
            manual_attachments_data = [x for x in wizard.mail_attachments_widget or [] if x.get('manual')]

            attachment = self.env['ir.attachment'].search([
                ('res_model', '=', 'account.move'),
                ('res_id', '=', wizard.move_id.id),
            ], order='id desc', limit=1)

            if attachment:
                wizard.mail_attachments_widget = [{
                    'id': attachment.id,
                    'name': attachment.name,
                    'mimetype': attachment.mimetype,
                    'index_content': '',
                    'manual': False,
                }] + manual_attachments_data
            else:
                result = super()._compute_mail_attachments_widget()
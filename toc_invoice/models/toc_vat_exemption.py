from odoo import models, api, _
import logging

_logger = logging.getLogger(__name__)


class AccountL10nPtVatExemptReason(models.Model):
    _inherit = 'account.l10n_pt.vat.exempt.reason'

    @api.model
    def cron_update_vat_exemption_reasons(self):
        toc_api = self.env['toc.api']
        reasons_data = toc_api.fetch_vat_exemption_reasons()

        if not reasons_data:
            return

        for data in reasons_data:
            attrs = data.get('attributes', {})
            toc_code = attrs.get('saft_exemption_code') or attrs.get('notation')
            toc_name = attrs.get('description') or attrs.get('name')

            if not toc_code:
                continue

            reason = self.search([('code', '=', toc_code)], limit=1)

            if reason:
                if reason.name != toc_name:
                    reason.write({'name': toc_name})
            else:
                self.create({
                    'code': toc_code,
                    'name': toc_name,
                })
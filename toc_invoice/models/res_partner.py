from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .toc_online_service import TocOnlineService


class ResPartner(models.Model):
    _inherit = 'res.partner'

    toc_online_id = fields.Char(
        string="TOConline ID",
        help="Customer ID in TOConline.",
        company_dependent=True,
    )

    def write(self, vals):
        result = super().write(vals)

        fields_to_check = {
            'name',
            'vat',
            'email',
            'website',
            'phone',
            'mobile',
            'country_id',
        }

        if any(field in vals for field in fields_to_check):
            toc_companies = self.env['res.company'].sudo().search([
                ('toc_online_enabled', '=', True),
            ])
            for partner in self:
                for company in toc_companies:
                    if partner.with_company(company).toc_online_id:
                        partner.update_customer_in_toconline(company=company)

        return result

    def update_customer_in_toconline(self, company=None):
        self.ensure_one()
        company = company or self.company_id or self.env.company
        service = TocOnlineService(company, self.env)
        service.update_customer(self)

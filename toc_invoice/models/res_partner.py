from odoo import models, fields, api, _
from odoo.exceptions import UserError

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
                    if partner.sudo().with_company(company).toc_online_id:
                        partner.sudo().update_customer_in_toconline(company=company)

        return result

    def update_customer_in_toconline(self, company=None):
        """
        Updates the customer's data on TOConline if a toc_online_id is present.
        """
        self.ensure_one()

        company = company or self.env.company
        if not company.toc_online_enabled:
            return

        access_token = self.env['toc.api'].get_access_token(company=company)

        customer_id = self.sudo().with_company(company).toc_online_id
        update_url = f"{company._get_toc_api_url()}/api/customers/{customer_id}"

        tax_number = self.vat.replace(" ", "").strip() if self.vat else "999999990"
        if len(tax_number) > 2 and tax_number[:2].isalpha():
            tax_number = tax_number[2:]
        email = self.email.strip() if self.email else ""

        customer_payload = {
            "data": {
                "type": "customers",
                "id": customer_id,
                "attributes": {
                    "tax_registration_number": tax_number,
                    "business_name": self.name,
                    "contact_name": self.name,
                    "website": self.website or "",
                    "phone_number": self.phone or "",
                    "mobile_number": self.mobile or "",
                    "email": email,
                    "observations": "",
                    "internal_observations": "",
                }
            }
        }

        response = self.env['toc.api'].toc_request(
            method='PATCH',
            url=update_url,
            payload=customer_payload,
            access_token=access_token
        )

        if response.status_code not in (200, 204):
            raise UserError(_("Error updating customer in TOConline: %s") % response.text)
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.addons.toc_invoice.utils import TOC_BASE_URL

class ResPartner(models.Model):
    _inherit = 'res.partner'

    toc_online_id = fields.Char(string="TOConline ID", help="Customer ID in TOConline.")

    def write(self, vals):
        result = super().write(vals)

        # Avoids unnecessary calls in case of bulk creation or when there are no relevant changes.

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
            for partner in self:
                if partner.toc_online_id:
                    partner.update_customer_in_toconline()

        return result

    def update_customer_in_toconline(self):
        """
        Updates the customer's data on TOConline if a toc_online_id is present.
        """
        self.ensure_one()

        access_token = self.env['toc.api'].get_access_token()  # ajuste com a forma como seu token é gerado

        customer_id = self.toc_online_id
        update_url = f"{TOC_BASE_URL}/api/customers/{customer_id}"

        tax_number = self.vat.replace(" ", "").strip() if self.vat else "999999990"
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
from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo import _


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    l10npt_vat_exempt_reason = fields.Many2one(
        "account.l10n_pt.vat.exempt.reason",
        string="VAT Exempt Reason",
        compute="_compute_l10npt_vat_exempt_reason",
        store=True,
        readonly=False,
    )

    @api.depends("tax_id")
    def _compute_l10npt_vat_exempt_reason(self):
        for line in self:
            zero_tax = line.tax_id.filtered(
                lambda t: t.amount == '0' and t.type_tax_use == "sale"
            )

            if zero_tax:
                # pega motivo padrão M01 (Artigo 53º)
                reason = self.env["account.l10n_pt.vat.exempt.reason"].search(
                    [("code", "=", "M01")],
                    limit=1,
                )
                line.l10npt_vat_exempt_reason = reason
            else:
                line.l10npt_vat_exempt_reason = False


    @api.constrains("tax_id", "l10npt_vat_exempt_reason")
    def _check_vat_exempt_reason(self):
        for line in self:
            zero_tax = line.tax_id.filtered(
                lambda t: t.amount == '0' and t.type_tax_use == "sale"
            )

            if zero_tax and not line.l10npt_vat_exempt_reason:
                raise ValidationError(
                    _("VAT Exempt Reason is required when tax is 0%.")
                )
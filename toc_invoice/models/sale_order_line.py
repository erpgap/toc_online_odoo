from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo import _


class SaleOrder(models.Model):
    _inherit = "sale.order"

    l10npt_vat_exempt_reason = fields.Many2one(
        "account.l10n_pt.vat.exempt.reason",
        string="VAT Exempt Reason",
    )

    @api.constrains("order_line", "l10npt_vat_exempt_reason")
    def _check_vat_exempt_reason(self):
        for order in self:
            if not order.company_id.toc_online_enabled:
                continue
            zero_tax_lines = order.order_line.filtered(
                lambda l: any(round(t.amount, 2) == 0.0 for t in l.tax_ids.filtered(
                    lambda t: t.type_tax_use == "sale"
                ))
            )
            if zero_tax_lines and not order.l10npt_vat_exempt_reason:
                raise ValidationError(
                    _("Esta encomenda possui linhas com IVA 0%%. É obrigatório informar o motivo de isenção.")
                )

    def _create_invoices(self, grouped=False, final=False, date=None):
        invoices = super()._create_invoices(grouped=grouped, final=final, date=date)
        for order in self:
            if order.l10npt_vat_exempt_reason:
                invoices.filtered(lambda m: m.invoice_origin == order.name).write({
                    "l10npt_vat_exempt_reason": order.l10npt_vat_exempt_reason.id
                })
        return invoices


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    @api.constrains("tax_ids", "state")
    def _check_tax_required(self):
        product_lines = self.filtered(
            lambda l: not l.display_type
            and l.product_id
            and l.order_id.company_id.toc_online_enabled
            and l.order_id.state in ('sale', 'done')
        )
        for line in product_lines:
            if not line.tax_ids:
                raise ValidationError(
                    _("A linha '%s' precisa ter um imposto definido.")
                    % line.product_id.display_name
                )

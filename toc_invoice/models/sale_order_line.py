from odoo import models, fields, api, Command
from odoo.exceptions import ValidationError
from odoo import _


class SaleOrder(models.Model):
    _inherit = "sale.order"

    l10npt_vat_exempt_reason = fields.Many2one(
        "account.l10n_pt.vat.exempt.reason",
        string="VAT Exempt Reason",
    )

    @api.constrains("order_line")
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
            exempt_reason = None

            for line in order.order_line:
                tax = line.tax_ids.filtered(lambda t: t.type_tax_use == "sale")[:1]

                if tax and round(tax.amount or 0.0, 2) == 0:
                    if line.l10npt_vat_exempt_reason:
                        exempt_reason = line.l10npt_vat_exempt_reason.id
                        break

            if not exempt_reason and order.l10npt_vat_exempt_reason:
                exempt_reason = order.l10npt_vat_exempt_reason.id

            if exempt_reason:
                invoices.filtered(lambda m: m.invoice_origin == order.name).write({
                    "l10npt_vat_exempt_reason": exempt_reason
                })

        return invoices


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    l10npt_vat_exempt_reason = fields.Many2one(
        "account.l10n_pt.vat.exempt.reason",
        string="VAT Exempt Reason",
        compute="_compute_l10npt_vat_exempt_reason",
        store=True,
        readonly=False,
    )

    @api.constrains("tax_ids")
    def _check_tax_required(self):
        for line in self:
            if not line.tax_ids:
                raise ValidationError(
                    _("A linha '%s' precisa ter um imposto definido.")
                    % line.product_id.display_name
                )

    @api.depends("tax_ids")
    def _compute_l10npt_vat_exempt_reason(self):
        for line in self:
            zero_tax = line.tax_ids.filtered(
                lambda t: round(t.amount, 2) == 0.0 and t.type_tax_use == "sale"
            )

            if zero_tax and not line.l10npt_vat_exempt_reason:
                # pega motivo padrão M01 (Artigo 53º)
                reason = self.env["account.l10n_pt.vat.exempt.reason"].search(
                    [("code", "=", "M01")],
                    limit=1,
                )
                line.l10npt_vat_exempt_reason = reason
            elif not zero_tax:
                line.l10npt_vat_exempt_reason = False

    @api.constrains("tax_ids", "l10npt_vat_exempt_reason")
    def _check_vat_exempt_reason(self):
        for line in self:
            if not line.order_id.company_id.toc_online_enabled:
                continue
            zero_tax = line.tax_ids.filtered(
                lambda t: round(t.amount, 2) == 0 and t.type_tax_use == "sale"
            )

            if zero_tax and not line.l10npt_vat_exempt_reason:
                raise ValidationError(
                    _(
                        "A linha '%s' possui IVA 0%%. É obrigatório informar o motivo de isenção."
                    )
                    % line.product_id.display_name
                )

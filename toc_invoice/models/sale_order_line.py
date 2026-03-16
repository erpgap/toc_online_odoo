from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo import _
from odoo.exceptions import UserError
from odoo import Command

class RepairOrder(models.Model):
    _inherit = "repair.order"

    class RepairOrder(models.Model):
        _inherit = "repair.order"

        def action_create_sale_order(self):
            res = super().action_create_sale_order()

            for repair in self:
                if repair.sale_order_id:
                    for move in repair.move_ids:
                        if move.sale_line_id and move.tax_id:
                            move.sale_line_id.tax_id = [(6, 0, move.tax_id.ids)]

            return res


class StockMove(models.Model):
    _inherit = "stock.move"

    tax_id = fields.Many2many(
        "account.tax",
        string="Taxes",
        domain=[("type_tax_use", "=", "sale")],
    )

    def _create_repair_sale_order_line(self):
        SaleOrderLine = self.env['sale.order.line']

        for move in self:
            if not move.repair_id.sale_order_id:
                continue

            order = move.repair_id.sale_order_id

            taxes = move.tax_id.ids or move.product_id.taxes_id.filtered(
                lambda t: t.type_tax_use == "sale"
            ).ids

            vals = {
                "order_id": order.id,
                "product_id": move.product_id.id,
                "name": move.product_id.display_name,
                "product_uom_qty": move.product_uom_qty,
                "price_unit": move.product_id.lst_price,
                "tax_id": [(6, 0, taxes)],
            }

            line = SaleOrderLine.create(vals)
            move.sale_line_id = line.id

class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _create_invoices(self, grouped=False, final=False, date=None):
        invoices = super()._create_invoices(grouped=grouped, final=final, date=date)

        for order in self:
            exempt_reason = None

            for line in order.order_line:
                tax = line.tax_id.filtered(lambda t: t.type_tax_use == "sale")[:1]

                if tax and round(tax.amount or 0.0, 2) == 0:
                    if line.l10npt_vat_exempt_reason:
                        exempt_reason = line.l10npt_vat_exempt_reason.id
                        break

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

    @api.constrains("tax_id")
    def _check_tax_required(self):
        for line in self:
            if not line.tax_id:
                raise ValidationError(
                    _("A linha '%s' precisa ter um imposto definido.")
                    % line.product_id.display_name
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
                lambda t: round(t.amount, 2) == 0 and t.type_tax_use == "sale"
            )

            if zero_tax and not line.l10npt_vat_exempt_reason:
                raise ValidationError(
                    _(
                        "A linha '%s' possui IVA 0%%. É obrigatório informar o motivo de isenção."
                    )
                    % line.product_id.display_name
                )
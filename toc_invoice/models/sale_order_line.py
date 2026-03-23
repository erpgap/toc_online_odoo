from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo import _
from odoo.exceptions import UserError
from odoo import Command

class RepairOrder(models.Model):
    _inherit = "repair.order"

    l10npt_vat_exempt_reason = fields.Many2one(
        "account.l10n_pt.vat.exempt.reason", string="VAT Exempt Reason"
    )

    @api.constrains("move_ids", "l10npt_vat_exempt_reason")
    def _check_vat_exempt_reason(self):
        for repair in self:
            has_zero_tax = False

            for move in repair.move_ids:
                taxes = move.tax_id or move.product_id.taxes_id.filtered(
                    lambda t: t.type_tax_use == "sale"
                )

                zero_tax = taxes.filtered(
                    lambda t: round(t.amount, 2) == 0.0 and t.type_tax_use == "sale"
                )

                if zero_tax:
                    has_zero_tax = True
                    break

            if has_zero_tax and not repair.l10npt_vat_exempt_reason:
                raise ValidationError(
                    _("Existe IVA 0%% nas linhas do reparo. O motivo de isenção é obrigatório.")
                )

    def action_create_sale_order(self):
        res = super().action_create_sale_order()

        for repair in self:
            sale = repair.sale_order_id
            if not sale:
                continue

            # ✅ 1. PASSAR PARA O SALE ORDER
            sale.l10npt_vat_exempt_reason = repair.l10npt_vat_exempt_reason

            has_zero_tax = False

            for move in repair.move_ids:
                if not move.sale_line_id:
                    continue

                line = move.sale_line_id

                # aplica taxes
                taxes = move.tax_id.ids or move.product_id.taxes_id.filtered(
                    lambda t: t.type_tax_use == "sale"
                ).ids

                line.tax_id = [(6, 0, taxes)]

                # verifica IVA 0%
                zero_tax = line.tax_id.filtered(
                    lambda t: round(t.amount, 2) == 0.0 and t.type_tax_use == "sale"
                )

                if zero_tax:
                    has_zero_tax = True

                    # ✅ 2. PASSAR PARA SALE ORDER LINE
                    if repair.l10npt_vat_exempt_reason:
                        line.l10npt_vat_exempt_reason = repair.l10npt_vat_exempt_reason

            # ✅ 3. VALIDAÇÃO FINAL
            if has_zero_tax and not repair.l10npt_vat_exempt_reason:
                raise ValidationError(
                    _("Este reparo possui produtos com IVA 0%. Informe o motivo de isenção.")
                )

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
            repair = move.repair_id

            taxes = move.tax_id.ids or move.product_id.taxes_id.filtered(
                lambda t: t.type_tax_use == "sale"
            ).ids

            line = SaleOrderLine.create({
                "order_id": order.id,
                "product_id": move.product_id.id,
                "name": move.product_id.display_name,
                "product_uom_qty": move.product_uom_qty,
                "price_unit": move.product_id.lst_price,
                "tax_id": [(6, 0, taxes)],
            })

            # ✅ IVA 0 → preencher motivo
            zero_tax = line.tax_id.filtered(
                lambda t: round(t.amount, 2) == 0.0 and t.type_tax_use == "sale"
            )

            if zero_tax and repair.l10npt_vat_exempt_reason:
                line.l10npt_vat_exempt_reason = repair.l10npt_vat_exempt_reason

            move.sale_line_id = line.id

class SaleOrder(models.Model):
    _inherit = "sale.order"

    l10npt_vat_exempt_reason = fields.Many2one(
        "account.l10n_pt.vat.exempt.reason",
        string="VAT Exempt Reason"
    )

    @api.constrains("order_line", "l10npt_vat_exempt_reason")
    def _check_vat_exempt_reason(self):
        for order in self:
            has_zero_tax = False

            for line in order.order_line:
                zero_tax = line.tax_id.filtered(
                    lambda t: round(t.amount, 2) == 0.0 and t.type_tax_use == "sale"
                )

                if zero_tax:
                    has_zero_tax = True
                    break

            if has_zero_tax and not order.l10npt_vat_exempt_reason:
                raise ValidationError(
                    _("Este pedido possui linhas com IVA 0%%. É obrigatório informar o motivo de isenção.")
                )

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
                lambda t: round(t.amount, 2) == 0.0 and t.type_tax_use == "sale"
            )

            if zero_tax:
                if not line.l10npt_vat_exempt_reason:
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
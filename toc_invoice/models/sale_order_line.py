from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class RepairOrder(models.Model):
    _inherit = "repair.order"

    l10npt_vat_exempt_reason = fields.Many2one(
        "account.l10n_pt.vat.exempt.reason", string="VAT Exempt Reason"
    )

    @api.constrains("move_ids", "l10npt_vat_exempt_reason")
    def _check_vat_exempt_reason(self):
        toc_repairs = self.filtered(lambda r: r.company_id.toc_online_enabled)
        for repair in toc_repairs:
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

            sale.l10npt_vat_exempt_reason = repair.l10npt_vat_exempt_reason

            has_zero_tax = False

            for move in repair.move_ids:
                if not move.sale_line_id:
                    continue

                line = move.sale_line_id

                taxes = move.tax_id.ids or move.product_id.taxes_id.filtered(
                    lambda t: t.type_tax_use == "sale"
                ).ids

                line.tax_id = [(6, 0, taxes)]

                zero_tax = line.tax_id.filtered(
                    lambda t: round(t.amount, 2) == 0.0 and t.type_tax_use == "sale"
                )

                if zero_tax:
                    has_zero_tax = True

            if repair.company_id.toc_online_enabled and has_zero_tax and not repair.l10npt_vat_exempt_reason:
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

            move.sale_line_id = line.id

class SaleOrder(models.Model):
    _inherit = "sale.order"

    l10npt_vat_exempt_reason = fields.Many2one(
        "account.l10n_pt.vat.exempt.reason",
        string="VAT Exempt Reason",
    )

    @api.constrains("order_line", "l10npt_vat_exempt_reason")
    def _check_vat_exempt_reason(self):
        toc_orders = self.filtered(lambda o: o.company_id.toc_online_enabled)
        for order in toc_orders:
            has_zero_tax = any(
                line.tax_id.filtered(
                    lambda t: round(t.amount, 2) == 0.0 and t.type_tax_use == "sale"
                )
                for line in order.order_line
            )
            if has_zero_tax and not order.l10npt_vat_exempt_reason:
                raise ValidationError(
                    _("Este pedido possui linhas com IVA 0%%. É obrigatório informar o motivo de isenção.")
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

    @api.constrains("tax_id", "state")
    def _check_tax_required(self):
        product_lines = self.filtered(
            lambda l: not l.display_type
            and l.product_id
            and l.order_id.company_id.toc_online_enabled
            and l.order_id.state in ('sale', 'done')
        )
        for line in product_lines:
            if not line.tax_id:
                raise ValidationError(
                    _("A linha '%s' precisa ter um imposto definido.")
                    % line.product_id.display_name
                )

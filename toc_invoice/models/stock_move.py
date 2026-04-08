from odoo import models, fields, Command


class StockMove(models.Model):
    _inherit = "stock.move"

    tax_id = fields.Many2many(
        "account.tax",
        string="Taxes",
        domain=[("type_tax_use", "=", "sale")],
    )

    def _get_new_picking_values(self):
        vals = super()._get_new_picking_values()
        sale_order = self.sale_line_id.order_id[:1]
        if sale_order and sale_order.l10npt_vat_exempt_reason:
            vals["l10npt_vat_exempt_reason"] = sale_order.l10npt_vat_exempt_reason.id
        return vals

    def _create_repair_sale_order_line(self):
        SaleOrderLine = self.env["sale.order.line"]
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
                "tax_ids": [Command.set(taxes)],
            }
            if move.repair_id.l10npt_vat_exempt_reason:
                vals["l10npt_vat_exempt_reason"] = move.repair_id.l10npt_vat_exempt_reason.id
            line = SaleOrderLine.create(vals)
            move.sale_line_id = line.id

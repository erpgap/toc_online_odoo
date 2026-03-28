from odoo import models, fields, api, Command, _
from odoo.exceptions import ValidationError


class RepairOrder(models.Model):
    _inherit = "repair.order"

    l10npt_vat_exempt_reason = fields.Many2one(
        "account.l10n_pt.vat.exempt.reason",
        string="VAT Exempt Reason",
    )

    @api.constrains("move_ids", "l10npt_vat_exempt_reason")
    def _check_vat_exempt_reason(self):
        for repair in self:
            if not repair.company_id.toc_online_enabled:
                continue
            zero_tax_moves = repair.move_ids.filtered(
                lambda m: any(round(t.amount, 2) == 0.0 for t in m.tax_id)
            )
            if zero_tax_moves and not repair.l10npt_vat_exempt_reason:
                raise ValidationError(
                    _("Este pedido possui linhas com IVA 0%%. É obrigatório informar o motivo de isenção.")
                )

    def action_create_sale_order(self):
        res = super().action_create_sale_order()
        for repair in self:
            if repair.sale_order_id:
                if repair.l10npt_vat_exempt_reason:
                    repair.sale_order_id.l10npt_vat_exempt_reason = repair.l10npt_vat_exempt_reason
                for move in repair.move_ids:
                    if move.sale_line_id and move.tax_id:
                        move.sale_line_id.tax_ids = [Command.set(move.tax_id.ids)]
        return res

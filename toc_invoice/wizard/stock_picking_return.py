from odoo import models


class StockReturnPicking(models.TransientModel):
    _inherit = "stock.return.picking"

    def _prepare_picking_default_values_based_on(self, picking):
        vals = super()._prepare_picking_default_values_based_on(picking)
        if picking.l10npt_vat_exempt_reason:
            vals["l10npt_vat_exempt_reason"] = picking.l10npt_vat_exempt_reason.id
        return vals

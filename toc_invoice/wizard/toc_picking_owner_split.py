from markupsafe import Markup

from odoo import models, fields, api, _


class TocPickingOwnerSplitWizard(models.TransientModel):
    _name = "toc.picking.owner.split.wizard"
    _description = "Split Transfer by Stock Owner"

    pick_ids = fields.Many2many("stock.picking", string="Transfers")
    split_summary = fields.Html(
        string="Summary", compute="_compute_split_summary", sanitize=False,
    )

    @api.depends("pick_ids")
    def _compute_split_summary(self):
        for wizard in self:
            wizard.split_summary = wizard._build_split_summary()

    def _build_split_summary(self):
        """Product count per owner, with the document each one will get."""
        self.ensure_one()
        summary = Markup()
        for picking in self.pick_ids:
            groups = picking._toc_owner_groups()
            if len(groups) <= 1:
                continue
            summary += Markup("<p class='mb-1'><b>%s</b></p><ul>") % picking.display_name
            for owner, move_lines in groups.items():
                summary += Markup("<li>%s &mdash; <i>%s</i>: %s</li>") % (
                    owner.display_name if owner else _("Our company"),
                    _("Guia de Transporte") if owner else _("Guia de Remessa"),
                    _("%s products", len(move_lines.product_id)),
                )
            summary += Markup("</ul>")
        return summary

    def action_confirm(self):
        picking_ids = self.env.context.get("button_validate_picking_ids") or self.pick_ids.ids
        pickings = self.env["stock.picking"].browse(picking_ids)
        pickings |= pickings._toc_split_by_owner()
        return pickings.with_context(
            button_validate_picking_ids=pickings.ids,
            skip_owner_split=True,
        ).button_validate()

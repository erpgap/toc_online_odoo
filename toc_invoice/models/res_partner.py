from odoo import models, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    toc_online_id = fields.Char(string="TOConline ID", help="Customer ID in TOConline.")

from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'  # Estende o modelo res.company

    # Adiciona o campo toc_company_id
    toc_company_id = fields.Char(string="ID da Empresa no TOConline")

    # Adiciona o campo toc_cash_account_id
    toc_cash_account_id = fields.Char(string="ID da Conta de Caixa no TOConline")
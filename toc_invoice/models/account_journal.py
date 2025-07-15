import logging
import requests

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

from odoo.addons.toc_invoice.utils import TOC_BASE_URL

_logger = logging.getLogger(__name__)


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    send_to_toconline = fields.Boolean(
        string="Send to TOConline",
        default=False,
        help="If unchecked, this journal's invoices will not be automatically sent to TOConline upon confirmation."
    )

# -*- coding: utf-8 -*-
from odoo import fields, models


class StockPicking(models.Model):
    """Add a field named 'tracking_status' in 'stock.picking' to have the
    status of the delivery """
    _inherit = 'stock.picking'

    tracking_status = fields.Text(string='Tracking Status',
                                  help="Status of the picking")

from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    show_on_hand_qty = fields.Boolean(
        string='Show On Hand Qty',
        compute='_compute_show_on_hand_qty',
        store=False,
        help='Technical field to control visibility of On Hand Qty column'
    )
    
    @api.depends()
    def _compute_show_on_hand_qty(self):
        """Compute whether to show On Hand Qty column based on settings"""
        show_qty = self.env['ir.config_parameter'].sudo().get_param(
            'ox_sale_negative_stock.show_on_hand_qty_in_sale_order_line', 
            'False'
        ) == 'True'
        for order in self:
            order.show_on_hand_qty = show_qty

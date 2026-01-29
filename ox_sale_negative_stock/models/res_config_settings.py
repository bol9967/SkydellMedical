from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    no_negative_stock_sale = fields.Boolean(
        string='No Negative Stock Sale',
        default=False,
        help='When enabled, this feature prevents products with zero stock from being visible in the search list when selecting products in sale order lines (Sale app only, not website/e-commerce).\n\n'
             'What gets hidden from search:\n'
             '• Physical products (Goods) that have stock tracking enabled and are currently out of stock (quantity = 0)\n\n'
             'What always remains visible in search:\n'
             '• Service products (like delivery fees, consulting services, etc.)\n'
             '• Combo products\n'
             '• Physical products without stock tracking\n'
             '• Physical products with stock tracking that have available inventory\n\n'
             'This helps prevent selling products that are out of stock and ensures only available items can be added to sale orders.\n\n'
             'Note: This setting only applies to the Sale app. Website/e-commerce orders are not affected and continue to use their own stock control settings.',
        config_parameter='ox_sale_negative_stock.no_negative_stock_sale'
    )
    
    display_zero_stock_in_search = fields.Boolean(
        string='Display Zero Stock Products in Search',
        default=False,
        help='When enabled, products with zero stock will be visible in the product search, but you still cannot add them to sale orders (validation will prevent it).\n\n'
             'Use this option if you want to see out-of-stock products in the search list for reference, but still prevent them from being added to orders.',
        config_parameter='ox_sale_negative_stock.display_zero_stock_in_search'
    )
    
    show_on_hand_qty_in_sale_order_line = fields.Boolean(
        string='Show On Hand Qty in Sale Order Line',
        default=False,
        help='When enabled, displays an "On Hand Qty" column in sale order lines. The column shows:\n'
             '• "Service" - when the product type is Service\n'
             '• "Combo" - when the product type is Combo\n'
             '• "Not Tracked" - when the product is a physical product (Goods) without stock tracking enabled\n'
             '• Actual stock quantity - when the product is a physical product (Goods) with stock tracking enabled',
        config_parameter='ox_sale_negative_stock.show_on_hand_qty_in_sale_order_line'
    )

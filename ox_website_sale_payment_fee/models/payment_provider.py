# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    payment_fee_enabled = fields.Boolean(
        string="Enable Payment Processing Fee",
        default=False,
        help="Enable processing fee for this payment provider"
    )
    
    payment_fee_percentage = fields.Float(
        string="Payment Fee Percentage",
        default=4.0,
        digits=(16, 2),
        help="Percentage of order total to charge as processing fee (e.g., 4.0 for 4%)"
    )
    
    payment_fee_product_id = fields.Many2one(
        string="Payment Fee Product",
        comodel_name='product.product',
        domain=[('type', '=', 'service')],
        help="Product to use for the payment processing fee line item. "
             "If not set, a default product will be created."
    )


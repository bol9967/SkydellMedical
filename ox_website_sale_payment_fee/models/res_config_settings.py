# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    payment_fee_enabled = fields.Boolean(
        string="Enable Payment Processing Fee",
        config_parameter='ox_website_sale_payment_fee.enabled',
        default=True,
        help="Enable 4% card processing fee for online payments on website orders"
    )
    
    payment_fee_percentage = fields.Float(
        string="Payment Fee Percentage",
        config_parameter='ox_website_sale_payment_fee.fee_percentage',
        default=4.0,
        digits=(16, 2),
        help="Percentage of order total to charge as processing fee (e.g., 4.0 for 4%)"
    )
    
    payment_fee_product_id = fields.Many2one(
        string="Payment Fee Product",
        comodel_name='product.product',
        config_parameter='ox_website_sale_payment_fee.product_id',
        domain=[('type', '=', 'service')],
        help="Product to use for the payment processing fee line item"
    )

    @api.model
    def get_values(self):
        """Get configuration values."""
        res = super().get_values()
        res.update(
            payment_fee_enabled=self.env['ir.config_parameter'].sudo().get_param(
                'ox_website_sale_payment_fee.enabled', 'True'
            ) == 'True',
            payment_fee_percentage=float(
                self.env['ir.config_parameter'].sudo().get_param(
                    'ox_website_sale_payment_fee.fee_percentage', '4.0'
                )
            ),
            payment_fee_product_id=int(
                self.env['ir.config_parameter'].sudo().get_param(
                    'ox_website_sale_payment_fee.product_id', '0'
                ) or '0'
            ) or False,
        )
        return res

    def set_values(self):
        """Set configuration values."""
        super().set_values()
        self.env['ir.config_parameter'].sudo().set_param(
            'ox_website_sale_payment_fee.enabled', 'True' if self.payment_fee_enabled else 'False'
        )
        self.env['ir.config_parameter'].sudo().set_param(
            'ox_website_sale_payment_fee.fee_percentage', str(self.payment_fee_percentage)
        )
        if self.payment_fee_product_id:
            self.env['ir.config_parameter'].sudo().set_param(
                'ox_website_sale_payment_fee.product_id', str(self.payment_fee_product_id.id)
            )


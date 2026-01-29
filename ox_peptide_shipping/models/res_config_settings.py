from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    peptide_category_id = fields.Many2one(
        'product.public.category',
        string='Peptide eCommerce Category',
        help='Select the eCommerce category for Peptide products.',
        config_parameter='ox_peptide_shipping.peptide_category_id'
    )

    enable_peptide_discount = fields.Boolean(
        string='Enable Peptide Discount',
        help='Enable automatic discount for peptide orders above threshold.'
    )

    peptide_discount_percentage = fields.Float(
        string='Peptide Discount Percentage',
        help='Discount percentage to apply for peptide orders above threshold (e.g., 10.0 for 10%).',
        config_parameter='ox_peptide_shipping.peptide_discount_percentage'
    )

    def get_values(self):
        """Override to properly read False values from config parameters."""
        res = super().get_values()
        config_param = self.env['ir.config_parameter'].sudo()
        
        # Read enable_peptide_discount - ensure False is properly handled
        enable_param = config_param.get_param('ox_peptide_shipping.enable_peptide_discount')
        if enable_param is not None:
            res['enable_peptide_discount'] = enable_param == 'True'
        else:
            # If parameter doesn't exist, default to False (not True)
            res['enable_peptide_discount'] = False
        
        # Read peptide_discount_percentage
        percentage_param = config_param.get_param('ox_peptide_shipping.peptide_discount_percentage')
        if percentage_param is not None:
            try:
                res['peptide_discount_percentage'] = float(percentage_param)
            except (ValueError, TypeError):
                res['peptide_discount_percentage'] = 0.0
        else:
            res['peptide_discount_percentage'] = 0.0
        
        return res

    def set_values(self):
        """Override to ensure False and 0 values are properly saved."""
        # Call super() first to let Odoo handle config_parameter fields
        super().set_values()
        # Then explicitly overwrite to ensure False and 0 are saved correctly
        config_param = self.env['ir.config_parameter'].sudo()
        # Force save as string 'False' or 'True' (not empty string or None)
        config_param.set_param(
            'ox_peptide_shipping.enable_peptide_discount',
            'True' if self.enable_peptide_discount else 'False'
        )
        # Force save percentage as string (including '0.0')
        config_param.set_param(
            'ox_peptide_shipping.peptide_discount_percentage',
            str(self.peptide_discount_percentage)
        )


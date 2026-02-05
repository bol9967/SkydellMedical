from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    enable_manager_commission = fields.Boolean(
        string='Enable Manager Commission',
        help='When enabled, sales team managers will receive commission on sales made by their team members. '
             'Manager commission rates are configured in the Commission Plans. '
             'When disabled, only salesperson and admin commissions will be calculated.'
    )
    
    @api.model
    def get_values(self):
        """Get configuration values"""
        res = super(ResConfigSettings, self).get_values()
        # Get the parameter value, default to True if not set
        enable_manager_commission = self.env['ir.config_parameter'].sudo().get_param(
            'ox_sales_commission.enable_manager_commission', 'True'
        ) == 'True'
        res.update(
            enable_manager_commission=enable_manager_commission
        )
        return res
    
    def set_values(self):
        """Set configuration values"""
        super(ResConfigSettings, self).set_values()
        # Explicitly save the parameter value
        # Use sudo() to ensure we have permission to write config parameters
        param_value = 'True' if self.enable_manager_commission else 'False'
        self.env['ir.config_parameter'].sudo().set_param(
            'ox_sales_commission.enable_manager_commission',
            param_value
        )
        # Clear cache to ensure the change takes effect immediately
        # Use registry.clear_cache() instead of deprecated model.clear_caches()
        self.env.registry.clear_cache()

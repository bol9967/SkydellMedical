# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Model representing res.config.settings"""
    _inherit = 'res.config.settings'

    delivery_tracking_api_key = fields.Char(
        'API Key',
        help='This API key is used to access Odoo and change the delivery'
             ' status')
    # Note: required=True removed from field definition because transient models
    # cannot enforce NOT NULL constraints at database level. Validation is done
    # in set_values() method instead.

    def set_values(self):
        """
        Overrides the base method to set the configured delivery tracking API
        key value in the 'ir.config_parameter' model.
        """
        res = super(ResConfigSettings, self).set_values()
        # Store the API key (can be empty, but if user wants to use it, they should set it)
        self.env['ir.config_parameter'].set_param(
            'stock.delivery_tracking_api_key', self.delivery_tracking_api_key or '')
        return res

    def get_values(self):
        """
        Overrides the base method to get the delivery tracking API key value
        from the 'ir.config_parameter' model and include it in the result.
        """
        res = super(ResConfigSettings, self).get_values()
        params = self.env['ir.config_parameter'].sudo()
        delivery_tracking_api_key = params.get_param(
            'stock.delivery_tracking_api_key')
        res.update(
            delivery_tracking_api_key=delivery_tracking_api_key,
        )
        return res

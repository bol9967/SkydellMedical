# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # OTP Rate Limiting Settings
    otp_resend_cooldown_seconds = fields.Integer(
        string="Resend Cooldown (seconds)",
        default=60,
        help="Minimum seconds between resend OTP requests",
        config_parameter='ox_partner_npi.otp_resend_cooldown_seconds'
    )
    
    otp_max_per_email_per_hour = fields.Integer(
        string="Max OTPs per Email (per hour)",
        default=5,
        help="Maximum number of OTP requests allowed per email address per hour",
        config_parameter='ox_partner_npi.otp_max_per_email_per_hour'
    )
    
    otp_max_per_ip_per_hour = fields.Integer(
        string="Max OTPs per IP (per hour)",
        default=10,
        help="Maximum number of OTP requests allowed per IP address per hour",
        config_parameter='ox_partner_npi.otp_max_per_ip_per_hour'
    )
    
    otp_max_per_email_per_10min = fields.Integer(
        string="Max OTPs per Email (per 10 minutes)",
        default=3,
        help="Maximum number of OTP requests allowed per email address per 10 minutes",
        config_parameter='ox_partner_npi.otp_max_per_email_per_10min'
    )
    
    @api.model
    def get_values(self):
        """Get current configuration values"""
        res = super(ResConfigSettings, self).get_values()
        get_param = self.env['ir.config_parameter'].sudo().get_param
        res.update(
            otp_resend_cooldown_seconds=int(get_param('ox_partner_npi.otp_resend_cooldown_seconds', 60)),
            otp_max_per_email_per_hour=int(get_param('ox_partner_npi.otp_max_per_email_per_hour', 5)),
            otp_max_per_ip_per_hour=int(get_param('ox_partner_npi.otp_max_per_ip_per_hour', 10)),
            otp_max_per_email_per_10min=int(get_param('ox_partner_npi.otp_max_per_email_per_10min', 3)),
        )
        return res
    
    def set_values(self):
        """Set configuration values"""
        super(ResConfigSettings, self).set_values()
        set_param = self.env['ir.config_parameter'].sudo().set_param
        set_param('ox_partner_npi.otp_resend_cooldown_seconds', self.otp_resend_cooldown_seconds)
        set_param('ox_partner_npi.otp_max_per_email_per_hour', self.otp_max_per_email_per_hour)
        set_param('ox_partner_npi.otp_max_per_ip_per_hour', self.otp_max_per_ip_per_hour)
        set_param('ox_partner_npi.otp_max_per_email_per_10min', self.otp_max_per_email_per_10min)

# -*- coding: utf-8 -*-

from odoo import models, fields, api, SUPERUSER_ID
from odoo.exceptions import ValidationError
import logging
import hashlib
import json
from datetime import datetime, timedelta, time

_logger = logging.getLogger(__name__)


class ReferralLinkClick(models.Model):
    """Track clicks on referral links"""
    _name = 'referral.link.click'
    _description = 'Referral Link Click Tracking'
    _order = 'click_date desc'
    _log_access = False  # Tracking model - no need for audit trail (create_uid, write_uid)

    referral_code = fields.Char(
        string='Referral Code',
        required=True,
        index=True,
        help='The referral code that was clicked'
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Referrer',
        compute='_compute_partner_id',
        store=True,
        index=True,
        help='The partner who owns this referral code'
    )
    ip_address = fields.Char(
        string='IP Address',
        index=True,
        help='IP address of the clicker'
    )
    user_agent = fields.Text(
        string='User Agent',
        help='Browser user agent string'
    )
    device_fingerprint = fields.Char(
        string='Device Fingerprint',
        index=True,
        help='Unique device identifier (hash of IP + User Agent)'
    )
    click_date = fields.Datetime(
        string='Click Date',
        default=fields.Datetime.now,
        required=True,
        index=True
    )
    converted = fields.Boolean(
        string='Converted',
        default=False,
        index=True,
        help='Did this click lead to a signup?'
    )
    converted_partner_id = fields.Many2one(
        'res.partner',
        string='Converted Partner',
        help='Partner created from this click'
    )
    conversion_date = fields.Datetime(
        string='Conversion Date',
        help='When the signup occurred'
    )
    utm_source = fields.Char(
        string='UTM Source',
        help='Marketing campaign source'
    )
    utm_medium = fields.Char(
        string='UTM Medium',
        help='Marketing campaign medium'
    )
    utm_campaign = fields.Char(
        string='UTM Campaign',
        help='Marketing campaign name'
    )
    utm_content = fields.Char(
        string='UTM Content',
        help='Marketing campaign content'
    )
    referrer_url = fields.Char(
        string='Referrer URL',
        help='URL where the click came from'
    )
    country_id = fields.Many2one(
        'res.country',
        string='Country',
        help='Country detected from IP (if geolocation enabled)'
    )
    is_unique = fields.Boolean(
        string='Unique Click',
        compute='_compute_is_unique',
        store=True,
        help='First click from this device/IP combination'
    )

    @api.depends('referral_code')
    def _compute_partner_id(self):
        """Find partner by referral code"""
        for click in self:
            if click.referral_code:
                # Use sudo to avoid access issues in public context
                partner = self.env['res.partner'].sudo().search([
                    ('referral_code', '=', click.referral_code)
                ], limit=1)
                click.partner_id = partner.id if partner else False

    @api.depends('device_fingerprint', 'click_date', 'referral_code')
    def _compute_is_unique(self):
        """Check if this is a unique click (first from this device)"""
        for click in self:
            if not click.device_fingerprint or not click.referral_code:
                click.is_unique = False
                continue
            
            # Check if there's an earlier click with same fingerprint and referral code
            earlier_click = self.search([
                ('device_fingerprint', '=', click.device_fingerprint),
                ('referral_code', '=', click.referral_code),
                ('click_date', '<', click.click_date),
                ('id', '!=', click.id)
            ], limit=1)
            
            click.is_unique = not bool(earlier_click)

    def _generate_device_fingerprint(self, ip_address, user_agent):
        """Generate device fingerprint from IP and User Agent"""
        if not ip_address or not user_agent:
            return False
        fingerprint_string = f"{ip_address}|{user_agent}"
        return hashlib.md5(fingerprint_string.encode()).hexdigest()

    @api.model
    def track_click(self, referral_code, ip_address=None, user_agent=None, 
                    utm_source=None, utm_medium=None, utm_campaign=None, 
                    utm_content=None, referrer_url=None):
        """Track a click on a referral link"""
        try:
            # Get IP from request if not provided
            if not ip_address:
                try:
                    from odoo.http import request
                    if request:
                        ip_address = request.httprequest.remote_addr
                except:
                    pass
            
            # Get User Agent from request if not provided
            if not user_agent:
                try:
                    from odoo.http import request
                    if request:
                        user_agent = request.httprequest.headers.get('User-Agent', '')
                except:
                    pass
            
            # Generate device fingerprint
            device_fingerprint = self._generate_device_fingerprint(ip_address, user_agent)
            
            # Create click record - use sudo() to bypass access rights and use system user
            # This ensures computed fields also write with valid user
            click_vals = {
                'referral_code': referral_code,
                'ip_address': ip_address,
                'user_agent': user_agent,
                'device_fingerprint': device_fingerprint,
                'utm_source': utm_source,
                'utm_medium': utm_medium,
                'utm_campaign': utm_campaign,
                'utm_content': utm_content,
                'referrer_url': referrer_url,
            }
            
            # Use sudo() to ensure all operations (including computed fields) use system user
            # The key is that self.env already has sudo() from controller call
            click = self.env['referral.link.click'].create(click_vals)
            _logger.info(f"Tracked click for referral code {referral_code}, click ID: {click.id}")
            return click
        except Exception as e:
            _logger.error(f"Error tracking click: {str(e)}", exc_info=True)
            return False

    def mark_as_converted(self, partner_id):
        """Mark this click as converted (led to signup)"""
        self.write({
            'converted': True,
            'converted_partner_id': partner_id,
            'conversion_date': fields.Datetime.now()
        })


class ReferralShare(models.Model):
    """Track social media shares of referral links"""
    _name = 'referral.share'
    _description = 'Referral Link Share Tracking'
    _order = 'share_date desc'
    _log_access = False  # Tracking model - no need for audit trail (create_uid, write_uid)

    referral_code = fields.Char(
        string='Referral Code',
        required=True,
        index=True
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Referrer',
        compute='_compute_partner_id',
        store=True,
        index=True
    )
    platform = fields.Selection([
        ('facebook', 'Facebook'),
        ('twitter', 'Twitter'),
        ('linkedin', 'LinkedIn'),
        ('whatsapp', 'WhatsApp'),
        ('email', 'Email'),
        ('copy_link', 'Copy Link'),
        ('other', 'Other'),
    ], string='Platform', required=True, index=True)
    share_date = fields.Datetime(
        string='Share Date',
        default=fields.Datetime.now,
        required=True,
        index=True
    )
    ip_address = fields.Char(string='IP Address')
    user_agent = fields.Text(string='User Agent')
    clicks_generated = fields.Integer(
        string='Clicks Generated',
        compute='_compute_clicks_generated',
        help='Number of clicks from this share'
    )
    conversions_generated = fields.Integer(
        string='Conversions Generated',
        compute='_compute_conversions_generated',
        help='Number of signups from this share'
    )

    @api.depends('referral_code')
    def _compute_partner_id(self):
        """Find partner by referral code"""
        for share in self:
            if share.referral_code:
                partner = self.env['res.partner'].sudo().search([
                    ('referral_code', '=', share.referral_code)
                ], limit=1)
                share.partner_id = partner.id if partner else False

    @api.depends('referral_code', 'share_date')
    def _compute_clicks_generated(self):
        """Count clicks generated from this share"""
        for share in self:
            if share.referral_code and share.share_date:
                clicks = self.env['referral.link.click'].search_count([
                    ('referral_code', '=', share.referral_code),
                    ('click_date', '>=', share.share_date),
                    ('utm_source', '=', share.platform)
                ])
                share.clicks_generated = clicks
            else:
                share.clicks_generated = 0

    @api.depends('referral_code', 'share_date')
    def _compute_conversions_generated(self):
        """Count conversions generated from this share"""
        for share in self:
            if share.referral_code and share.share_date:
                conversions = self.env['referral.link.click'].search_count([
                    ('referral_code', '=', share.referral_code),
                    ('click_date', '>=', share.share_date),
                    ('utm_source', '=', share.platform),
                    ('converted', '=', True)
                ])
                share.conversions_generated = conversions
            else:
                share.conversions_generated = 0

    @api.model
    def track_share(self, referral_code, platform, ip_address=None, user_agent=None):
        """Track a share of a referral link"""
        try:
            share_vals = {
                'referral_code': referral_code,
                'platform': platform,
                'ip_address': ip_address,
                'user_agent': user_agent,
            }
            # Use sudo() to ensure all operations (including computed fields) use system user
            # The key is that self.env already has sudo() from controller call
            share = self.env['referral.share'].create(share_vals)
            _logger.info(f"Tracked share for referral code {referral_code} on {platform}, share ID: {share.id}")
            return share
        except Exception as e:
            _logger.error(f"Error tracking share: {str(e)}", exc_info=True)
            return False


class ReferralFraudDetection(models.Model):
    """Track potential fraud indicators"""
    _name = 'referral.fraud.detection'
    _description = 'Referral Fraud Detection'
    _order = 'detection_date desc'
    _log_access = False  # Tracking model - no need for audit trail

    partner_id = fields.Many2one(
        'res.partner',
        string='Referrer',
        index=True
    )
    referral_code = fields.Char(
        string='Referral Code',
        index=True
    )
    detection_type = fields.Selection([
        ('duplicate_ip', 'Duplicate IP Address'),
        ('duplicate_device', 'Duplicate Device Fingerprint'),
        ('velocity_exceeded', 'Velocity Check Failed'),
        ('self_referral', 'Self Referral Attempt'),
        ('suspicious_pattern', 'Suspicious Pattern'),
    ], string='Detection Type', required=True, index=True)
    severity = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ], string='Severity', default='medium', required=True)
    description = fields.Text(string='Description')
    detection_date = fields.Datetime(
        string='Detection Date',
        default=fields.Datetime.now,
        required=True,
        index=True
    )
    ip_address = fields.Char(string='IP Address')
    device_fingerprint = fields.Char(string='Device Fingerprint')
    flagged_clicks = fields.Many2many(
        'referral.link.click',
        string='Flagged Clicks',
        help='Clicks flagged by this detection'
    )
    status = fields.Selection([
        ('pending', 'Pending Review'),
        ('reviewed', 'Reviewed'),
        ('false_positive', 'False Positive'),
        ('confirmed', 'Confirmed Fraud'),
    ], string='Status', default='pending', required=True, index=True)
    reviewed_by = fields.Many2one(
        'res.users',
        string='Reviewed By'
    )
    review_date = fields.Datetime(string='Review Date')
    review_notes = fields.Text(string='Review Notes')

    @api.model
    def check_duplicate_ip(self, referral_code, ip_address, time_window_hours=24):
        """Check for duplicate IP addresses within time window"""
        if not ip_address or not referral_code:
            return False
        
        cutoff_time = fields.Datetime.now() - timedelta(hours=time_window_hours)
        recent_clicks = self.env['referral.link.click'].search([
            ('referral_code', '=', referral_code),
            ('ip_address', '=', ip_address),
            ('click_date', '>=', cutoff_time)
        ])
        
        if len(recent_clicks) > 10:  # Threshold: more than 10 clicks from same IP
            self.sudo().create({
                'partner_id': self.env['res.partner'].sudo().search([
                    ('referral_code', '=', referral_code)
                ], limit=1).id,
                'referral_code': referral_code,
                'detection_type': 'duplicate_ip',
                'severity': 'high' if len(recent_clicks) > 50 else 'medium',
                'description': f'Multiple clicks ({len(recent_clicks)}) from same IP ({ip_address}) within {time_window_hours} hours',
                'ip_address': ip_address,
                'flagged_clicks': [(6, 0, recent_clicks.ids)]
            })
            return True
        return False

    @api.model
    def check_duplicate_device(self, referral_code, device_fingerprint, time_window_hours=24):
        """Check for duplicate device fingerprints"""
        if not device_fingerprint or not referral_code:
            return False
        
        cutoff_time = fields.Datetime.now() - timedelta(hours=time_window_hours)
        recent_clicks = self.env['referral.link.click'].search([
            ('referral_code', '=', referral_code),
            ('device_fingerprint', '=', device_fingerprint),
            ('click_date', '>=', cutoff_time)
        ])
        
        if len(recent_clicks) > 10:
            self.sudo().create({
                'partner_id': self.env['res.partner'].sudo().search([
                    ('referral_code', '=', referral_code)
                ], limit=1).id,
                'referral_code': referral_code,
                'detection_type': 'duplicate_device',
                'severity': 'high' if len(recent_clicks) > 50 else 'medium',
                'description': f'Multiple clicks ({len(recent_clicks)}) from same device within {time_window_hours} hours',
                'device_fingerprint': device_fingerprint,
                'flagged_clicks': [(6, 0, recent_clicks.ids)]
            })
            return True
        return False

    @api.model
    def check_velocity(self, referral_code, ip_address=None, device_fingerprint=None, max_clicks_per_hour=20):
        """Check if click velocity exceeds threshold"""
        if not referral_code:
            return False
        
        cutoff_time = fields.Datetime.now() - timedelta(hours=1)
        domain = [
            ('referral_code', '=', referral_code),
            ('click_date', '>=', cutoff_time)
        ]
        
        if ip_address:
            domain.append(('ip_address', '=', ip_address))
        if device_fingerprint:
            domain.append(('device_fingerprint', '=', device_fingerprint))
        
        recent_clicks = self.env['referral.link.click'].search(domain)
        
        if len(recent_clicks) > max_clicks_per_hour:
            self.sudo().create({
                'partner_id': self.env['res.partner'].sudo().search([
                    ('referral_code', '=', referral_code)
                ], limit=1).id,
                'referral_code': referral_code,
                'detection_type': 'velocity_exceeded',
                'severity': 'high' if len(recent_clicks) > max_clicks_per_hour * 2 else 'medium',
                'description': f'Velocity check failed: {len(recent_clicks)} clicks in last hour (limit: {max_clicks_per_hour})',
                'ip_address': ip_address,
                'device_fingerprint': device_fingerprint,
                'flagged_clicks': [(6, 0, recent_clicks.ids)]
            })
            return True
        return False

    @api.model
    def check_self_referral(self, referral_code, ip_address, device_fingerprint):
        """Check if someone is trying to refer themselves"""
        partner = self.env['res.partner'].search([
            ('referral_code', '=', referral_code)
        ], limit=1)
        
        if not partner:
            return False
        
        # Check if IP/device matches partner's recent activity
        # This is a simplified check - in production, you'd want more sophisticated matching
        user = partner.user_ids[0] if partner.user_ids else False
        if user:
            # Check if user logged in from same IP recently
            # Note: This requires login tracking which may not exist
            pass
        
        return False

    def action_mark_reviewed(self):
        """Mark fraud detection as reviewed"""
        self.write({
            'status': 'reviewed',
            'reviewed_by': self.env.user.id,
            'review_date': fields.Datetime.now()
        })

    def action_mark_false_positive(self):
        """Mark fraud detection as false positive"""
        self.write({
            'status': 'false_positive',
            'reviewed_by': self.env.user.id,
            'review_date': fields.Datetime.now()
        })

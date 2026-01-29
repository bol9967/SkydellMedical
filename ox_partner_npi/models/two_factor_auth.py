# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError
import secrets
import string
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)


class TwoFactorAuth(models.Model):
    _name = 'two.factor.auth'
    _description = 'Two-Factor Authentication OTP'
    _order = 'create_date desc'

    email = fields.Char(string='Email', required=True, index=True)
    otp_code = fields.Char(string='OTP Code', required=True, index=True)
    session_id = fields.Char(string='Session ID', required=True, index=True)
    is_verified = fields.Boolean(string='Verified', default=False, index=True)
    verified_at = fields.Datetime(string='Verified At')
    expires_at = fields.Datetime(string='Expires At', required=True, index=True)
    attempts = fields.Integer(string='Verification Attempts', default=0)
    max_attempts = fields.Integer(string='Max Attempts', default=3)
    ip_address = fields.Char(string='IP Address')
    user_agent = fields.Char(string='User Agent')
    create_date = fields.Datetime(string='Created At', readonly=True)

    @api.model
    def generate_otp(self, length=6):
        """Generate a random OTP code"""
        digits = string.digits
        return ''.join(secrets.choice(digits) for _ in range(length))

    @api.model
    def create_otp(self, email, session_id, ip_address=None, user_agent=None, expiry_minutes=10):
        """Create a new OTP for email verification"""
        # Invalidate any existing unverified OTPs for this email/session
        # Mark them as expired instead of deleting to preserve rate limiting history
        existing = self.search([
            ('email', '=', email),
            ('session_id', '=', session_id),
            ('is_verified', '=', False),
            ('expires_at', '>', fields.Datetime.now())
        ])
        if existing:
            # Mark as expired by setting expires_at to past
            existing.write({'expires_at': fields.Datetime.now() - timedelta(seconds=1)})

        # Generate new OTP
        otp_code = self.generate_otp()
        expires_at = fields.Datetime.now() + timedelta(minutes=expiry_minutes)

        otp_record = self.create({
            'email': email,
            'otp_code': otp_code,
            'session_id': session_id,
            'expires_at': expires_at,
            'ip_address': ip_address,
            'user_agent': user_agent,
        })

        _logger.info("OTP created for email: %s, session: %s, expires: %s", email, session_id, expires_at)
        return otp_record, otp_code

    def verify_otp(self, otp_code):
        """Verify the OTP code"""
        self.ensure_one()

        # Check if already verified
        if self.is_verified:
            raise ValidationError("This OTP has already been used.")

        # Check if expired
        if fields.Datetime.now() > self.expires_at:
            raise ValidationError("OTP code has expired. Please request a new one.")

        # Check max attempts
        if self.attempts >= self.max_attempts:
            raise ValidationError("Maximum verification attempts exceeded. Please request a new OTP.")

        # Increment attempts
        self.attempts += 1

        # Verify code
        if self.otp_code != otp_code:
            if self.attempts >= self.max_attempts:
                self.unlink()  # Delete after max attempts
            return False

        # Mark as verified
        self.is_verified = True
        self.verified_at = fields.Datetime.now()
        _logger.info("OTP verified successfully for email: %s, session: %s", self.email, self.session_id)
        return True

    @api.model
    def get_valid_otp(self, email, session_id):
        """Get a valid (unverified, not expired) OTP for email and session"""
        return self.search([
            ('email', '=', email),
            ('session_id', '=', session_id),
            ('is_verified', '=', False),
            ('expires_at', '>', fields.Datetime.now())
        ], limit=1, order='create_date desc')

    @api.model
    def cleanup_expired_otps(self):
        """Cleanup expired OTPs (can be called by cron)"""
        expired = self.search([
            ('expires_at', '<', fields.Datetime.now()),
            ('is_verified', '=', False)
        ])
        if expired:
            count = len(expired)
            expired.unlink()
            _logger.info("Cleaned up %d expired OTP records", count)
        return True

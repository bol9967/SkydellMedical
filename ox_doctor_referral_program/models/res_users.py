# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ResUsers(models.Model):
    _inherit = 'res.users'

    # Related fields to expose partner's referral information in user preferences
    partner_referral_code = fields.Char(
        string='Your Referral Code',
        related='partner_id.referral_code',
        readonly=True,
    )
    partner_referral_link = fields.Char(
        string='Your Referral Link',
        related='partner_id.referral_link',
        readonly=True,
    )
    partner_referred_doctors_count = fields.Integer(
        string='Your Referred Doctors Count',
        related='partner_id.referred_doctors_count',
        readonly=True,
    )
    partner_referral_qr_url = fields.Char(
        string='Referral QR Code URL',
        compute='_compute_partner_referral_qr_url',
    )

    @api.depends('partner_id.referral_code')
    def _compute_partner_referral_qr_url(self):
        for user in self:
            if user.partner_id.referral_code:
                user.partner_referral_qr_url = f'/referral/qr/{user.partner_id.referral_code}'
            else:
                user.partner_referral_qr_url = False

    @property
    def SELF_READABLE_FIELDS(self):
        """Allow users to read their own referral fields"""
        return super().SELF_READABLE_FIELDS + [
            'partner_referral_code',
            'partner_referral_link',
            'partner_referred_doctors_count',
            'partner_referral_qr_url',
        ]

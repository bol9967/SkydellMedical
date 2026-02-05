# -*- coding: utf-8 -*-

import secrets
import string
from odoo import models, fields, api, SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)

# Try to import request (available in HTTP context)
try:
    from odoo.http import request
except ImportError:
    request = None


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Referral fields
    referral_code = fields.Char(
        string='Referral Code',
        copy=False,
        index=True,
        help='Unique referral code for generating affiliate links'
    )
    referral_link = fields.Char(
        string='Referral Link',
        compute='_compute_referral_link',
        store=False,
        help='Full URL for referral link'
    )
    referred_by_id = fields.Many2one(
        'res.partner',
        string='Referred By',
        ondelete='set null',
        help='The doctor/partner who referred this doctor'
    )
    referral_level = fields.Integer(
        string='Referral Level',
        default=0,
        help='Level in referral chain: 0=Salesperson (internal user), 1=Doctor 1, 2=Doctor 2/3/4, 999=Company'
    )
    is_salesperson_onboarded = fields.Boolean(
        string='Salesperson-Onboarded Doctor',
        default=False,
        help='True if doctor was registered via salesperson referral link'
    )
    is_doctor_referred = fields.Boolean(
        string='Doctor-Referred',
        default=False,
        help='True if doctor was registered via another doctor referral link'
    )
    referral_type = fields.Selection([
        ('salesperson', 'Salesperson-Onboarded'),
        ('doctor_level_1', 'Doctor-Referred (Level 1)'),
        ('doctor_level_2', 'Doctor-Referred (Level 2+)'),
        ('company', 'Company Referral'),
    ], string='Referral Type', compute='_compute_referral_type', store=True)
    
    # Salesperson assignment (use native user_id field for commission tracking)
    # referral_salesperson_id is kept for tracking the original salesperson from referral chain
    referral_salesperson_id = fields.Many2one(
        'res.users',
        string='Referral Salesperson',
        help='Salesperson assigned via referral chain (tracking field)'
    )
    
    # User type from res.users model
    user_type = fields.Selection([
        ('internal', 'Internal User'),
        ('portal', 'Portal User'),
        ('public', 'Public User'),
        ('no_user', 'No User'),
    ], string='User Type', compute='_compute_user_type', store=True, readonly=True,
       help='Type of user linked to this partner (from res.users model)')
    
    # Referral chain tracking
    referred_doctors_ids = fields.One2many(
        'res.partner',
        'referred_by_id',
        string='Referred Doctors',
        help='Doctors referred by this doctor'
    )
    referred_doctors_count = fields.Integer(
        string='Referred Doctors Count',
        compute='_compute_referred_doctors_count',
        store=False
    )
    
    # Doctor 1 identification
    is_doctor_1 = fields.Boolean(
        string='Is Doctor 1',
        compute='_compute_is_doctor_1',
        store=True,
        recursive=True,
        help='True if this is the first doctor registered via a salesperson link'
    )
    doctor_1_id = fields.Many2one(
        'res.partner',
        string='Doctor 1',
        compute='_compute_doctor_1_id',
        store=False,
        help='The Doctor 1 in this referral chain (for promo rewards)'
    )
    
    # Analytics fields (computed from tracking data)
    total_clicks = fields.Integer(
        string='Total Clicks',
        compute='_compute_referral_stats',
        help='Total clicks on referral link'
    )
    unique_clicks = fields.Integer(
        string='Unique Clicks',
        compute='_compute_referral_stats',
        help='Unique clicks on referral link'
    )
    conversion_rate = fields.Float(
        string='Conversion Rate (%)',
        compute='_compute_referral_stats',
        help='Percentage of clicks that converted to signups'
    )
    total_revenue = fields.Monetary(
        string='Total Revenue',
        currency_field='currency_id',
        compute='_compute_referral_stats',
        help='Total revenue from referred doctors'
    )
    qr_code_url = fields.Char(
        string='QR Code URL',
        compute='_compute_qr_code_url',
        help='URL to generate QR code for this referral link'
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
        readonly=True
    )
    
    # Tracking relationships
    click_ids = fields.One2many(
        'referral.link.click',
        'partner_id',
        string='Clicks',
        readonly=True
    )
    share_ids = fields.One2many(
        'referral.share',
        'partner_id',
        string='Shares',
        readonly=True
    )
    fraud_detection_ids = fields.One2many(
        'referral.fraud.detection',
        'partner_id',
        string='Fraud Detections',
        readonly=True
    )

    @api.depends('is_salesperson_onboarded', 'is_doctor_referred', 'referral_level', 'referral_type')
    def _compute_referral_type(self):
        """Compute referral type based on flags and level

        Referral levels:
        - 0: Salesperson (internal user)
        - 1: Doctor 1 (first doctor referred by salesperson)
        - 2: Doctor 2/3/4 (referred by Doctor 1)
        - 999: Company referral
        """
        for partner in self:
            if partner.is_salesperson_onboarded and partner.referral_level == 1:
                partner.referral_type = 'salesperson'
            elif partner.is_doctor_referred and partner.referral_level == 2:
                partner.referral_type = 'doctor_level_1'
            elif partner.is_doctor_referred and partner.referral_level >= 3:
                partner.referral_type = 'doctor_level_2'
            else:
                partner.referral_type = 'company'

    @api.depends('user_ids', 'user_ids.share', 'user_ids.active', 'user_ids.groups_id')
    def _compute_user_type(self):
        """Compute user type from partner's OWN login user (user_ids)

        IMPORTANT: This checks user_ids (partner's own login), NOT user_id (salesperson field)

        Aligns with Odoo 18 native logic:
        - Internal User: has base.group_user → share = False
        - Portal User: has base.group_portal → share = True
        - Public User: has base.group_public → share = True
        - No User: no linked user or inactive

        Uses Odoo 18 native helper methods: _is_internal(), _is_portal(), _is_public()
        """
        for partner in self:
            # Check partner's OWN login user (user_ids), NOT salesperson field (user_id)
            partner_own_user = partner.user_ids[:1] if partner.user_ids else False
            if not partner_own_user or not partner_own_user.active:
                partner.user_type = 'no_user'
            else:
                # Use Odoo 18 native helper methods to determine user type
                # These methods check groups_id, which is more reliable than just checking share
                try:
                    if partner_own_user._is_public():
                        partner.user_type = 'public'
                    elif partner_own_user._is_portal():
                        partner.user_type = 'portal'
                    elif partner_own_user._is_internal():
                        partner.user_type = 'internal'
                    else:
                        # Fallback: use share field if helper methods don't work
                        # This handles edge cases or custom user types
                        if partner_own_user.share:
                            partner.user_type = 'portal'
                        else:
                            partner.user_type = 'internal'
                except Exception:
                    # Fallback to share field if helper methods fail
                    # Use partner_own_user (partner's own login), NOT partner.user_id (salesperson field)
                    if partner_own_user.share:
                        partner.user_type = 'portal'
                    else:
                        partner.user_type = 'internal'

    @api.depends('referred_doctors_ids')
    def _compute_referred_doctors_count(self):
        """Count referred doctors"""
        for partner in self:
            partner.referred_doctors_count = len(partner.referred_doctors_ids)

    @api.depends('is_salesperson_onboarded', 'referred_by_id', 'referred_by_id.user_id', 'referred_by_id.user_id.share', 'user_ids', 'user_ids.groups_id')
    def _compute_is_doctor_1(self):
        """Doctor 1 is the first doctor (portal user) registered via a salesperson (internal user) link

        Rules:
        - Doctor 1 must be a PORTAL USER (doctor), NOT an internal user (salesperson)
        - Doctor 1 must be referred by an internal user (salesperson) directly
        - OR be a direct signup (no referrer) and manually onboarded by salesperson
        - CANNOT be referred by another doctor/partner (even if that partner has an internal user)
        - Internal users themselves CANNOT be Doctor 1

        NOTE: user_id is the SALESPERSON field (assigned sales rep)
              user_ids is the partner's OWN login user(s)
              Internal user = has base.group_user in groups_id
        """
        user_group_id = self.env['ir.model.data']._xmlid_to_res_id('base.group_user')
        for partner in self:
            # CRITICAL: Internal users (salespersons) CANNOT be Doctor 1
            # Only portal users (doctors) can be Doctor 1
            # Check partner's OWN login user (user_ids), NOT the salesperson field (user_id)
            partner_own_user = partner.user_ids[:1] if partner.user_ids else False
            is_internal_user = False
            if partner_own_user:
                has_internal_group = user_group_id in partner_own_user.groups_id.ids
                is_internal_user = partner_own_user.active and has_internal_group

            if is_internal_user:
                # This partner's own login is an internal user - they are a salesperson, NOT a doctor
                partner.is_doctor_1 = False
                continue

            # Check if referred by internal user (salesperson) DIRECTLY
            # This means the referring partner itself must be linked to an internal user
            # AND the referring partner should NOT be a doctor (not have is_doctor_1 = True)
            # Note: We check is_doctor_1 directly but don't include it in @api.depends to avoid recursion warning
            is_referred_by_internal_user = False
            if partner.referred_by_id:
                referring_partner = partner.referred_by_id
                # Check if referring partner is linked to an internal user (their salesperson/user_id field)
                # For the REFERRER, we check user_id because we're checking if they ARE a salesperson
                # (the referrer's user_id points to themselves if they are an internal user)
                has_internal_user = (
                    referring_partner.user_id and
                    not referring_partner.user_id.share and
                    referring_partner.user_id.active
                )
                # CRITICAL: The referring partner should NOT be a doctor
                # If referred_by_id.is_doctor_1 is True, then we're being referred by a doctor, not salesperson
                # We access is_doctor_1 directly (not in depends) to avoid recursion warning
                is_referred_by_internal_user = (
                    has_internal_user and
                    not referring_partner.is_doctor_1
                )

            # Doctor 1:
            # 1. Must be salesperson-onboarded
            # 2. Must be referred by internal user directly (not via another doctor)
            # 3. OR have no referrer (direct signup/manual creation)
            # 4. Must NOT be an internal user themselves (checked above)
            partner.is_doctor_1 = (
                partner.is_salesperson_onboarded and
                (is_referred_by_internal_user or not partner.referred_by_id)
            )

    @api.depends('referred_by_id', 'referred_by_id.is_doctor_1', 'referred_by_id.referred_by_id', 'is_doctor_1')
    def _compute_doctor_1_id(self):
        """Find Doctor 1 in the referral chain by traversing up
        
        If current partner IS Doctor 1, returns False (empty) - they are Doctor 1 themselves.
        Otherwise, traverses up the referral chain to find Doctor 1.
        """
        for partner in self:
            # If this partner IS Doctor 1, they don't have a Doctor 1 above them
            if partner.is_doctor_1:
                partner.doctor_1_id = False
                continue
            
            doctor_1 = False
            current = partner.referred_by_id
            # Traverse up the referral chain (max depth protection)
            visited = set()
            max_depth = 10  # Prevent infinite loops
            depth = 0
            while current and current.id not in visited and depth < max_depth:
                visited.add(current.id)
                if current.is_doctor_1:
                    doctor_1 = current
                    break
                current = current.referred_by_id
                depth += 1
            partner.doctor_1_id = doctor_1

    @api.depends('referral_code')
    def _compute_referral_link(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://localhost:8069')
        for partner in self:
            if partner.referral_code:
                # Use tracking URL instead of direct signup URL
                partner.referral_link = f"{base_url}/ref/click/{partner.referral_code}"
            else:
                partner.referral_link = False

    @api.model
    def _generate_referral_code(self):
        """Generate a unique referral code"""
        while True:
            # Generate 8-character alphanumeric code
            code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            if not self.search([('referral_code', '=', code)], limit=1):
                return code

    @api.depends('click_ids', 'click_ids.converted')
    def _compute_referral_stats(self):
        """Compute referral statistics from tracking data"""
        for partner in self:
            if not partner.referral_code:
                partner.total_clicks = 0
                partner.unique_clicks = 0
                partner.conversion_rate = 0.0
                partner.total_revenue = 0.0
                continue
            
            clicks = partner.click_ids
            partner.total_clicks = len(clicks)
            partner.unique_clicks = len(clicks.filtered('is_unique'))
            
            # Calculate conversion rate
            converted_clicks = len(clicks.filtered('converted'))
            if partner.total_clicks > 0:
                partner.conversion_rate = (converted_clicks / partner.total_clicks) * 100
            else:
                partner.conversion_rate = 0.0
            
            # Calculate total revenue from referred partners
            referred_partners = self.env['res.partner'].search([
                ('referred_by_id', '=', partner.id)
            ])
            orders = self.env['sale.order'].search([
                ('partner_id', 'in', referred_partners.ids),
                ('state', 'in', ['sale', 'done'])
            ])
            partner.total_revenue = sum(orders.mapped('amount_total'))

    @api.depends('referral_code')
    def _compute_qr_code_url(self):
        """Compute QR code URL for referral link"""
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://localhost:8069')
        for partner in self:
            if partner.referral_code:
                partner.qr_code_url = f"{base_url}/ref/qrcode/{partner.referral_code}"
            else:
                partner.qr_code_url = False

    def action_generate_referral_code(self):
        """Generate referral code for this partner"""
        for partner in self:
            if not partner.referral_code:
                partner.referral_code = partner._generate_referral_code()
            else:
                raise UserError('This partner already has a referral code.')

    def action_view_qrcode(self):
        """Open QR code image in new window"""
        self.ensure_one()
        if not self.referral_code:
            raise UserError('No referral code available. Please generate one first.')
        
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://localhost:8069')
        qrcode_url = f"{base_url}/ref/qrcode/{self.referral_code}"
        
        return {
            'type': 'ir.actions.act_url',
            'url': qrcode_url,
            'target': 'new',
        }

    @api.model_create_multi
    def create(self, vals_list):
        """Auto-generate referral code and set referral level
        
        Coordinates with ox_own_contacts_visibility module:
        - ox_own_contacts_visibility sets user_id to creator in vals_list (if not set)
        - This module handles referral chain assignment AFTER creation
        - If referral chain exists, it overrides user_id assignment
        - If no referral chain and manually created by salesperson, keeps creator as user_id
        
        Also handles referral codes from session (for signup flows that bypass controller)
        """
        # Check for referral code in session/context (for signup flows)
        # This handles cases where other modules (like ox_partner_npi) bypass the controller
        referral_code = None

        # Try to get referral code from HTTP request session
        try:
            if request and hasattr(request, 'session'):
                session_referral = request.session.get('referral_code')
                _logger.info(
                    f"[res.partner.create] Session check: referral_code={session_referral}, "
                    f"session ID: {getattr(request.session, 'sid', 'N/A')}, "
                    f"session keys: {list(request.session.keys())}"
                )
                referral_code = session_referral
                if referral_code:
                    _logger.info(f"[res.partner.create] Found referral code in session: {referral_code}")
            else:
                _logger.info(f"[res.partner.create] No request or session available (request={request})")
        except (AttributeError, RuntimeError) as e:
            _logger.info(f"[res.partner.create] Could not access request session: {e}")

        # Also check context for referral code (set by controller)
        if not referral_code:
            referral_code = self.env.context.get('referral_code')
            if referral_code:
                _logger.info(f"[res.partner.create] Found referral code in context: {referral_code}")
            else:
                _logger.info(f"[res.partner.create] No referral code in context either. Context keys: {list(self.env.context.keys())}")
        
        # Process referral code for each partner if not already set
        for vals in vals_list:
            # Generate referral code if not provided
            if 'referral_code' not in vals or not vals.get('referral_code'):
                vals['referral_code'] = self._generate_referral_code()
            
            # If referral code found and referred_by_id not set, look it up
            if referral_code and 'referred_by_id' not in vals:
                referring_partner = self.get_partner_by_referral_code(referral_code)
                if referring_partner:
                    vals['referred_by_id'] = referring_partner.id
                    _logger.info(
                        f"[res.partner.create] Setting referred_by_id={referring_partner.id} "
                        f"from referral code {referral_code}"
                    )
        
        # Call super() - this will call ox_own_contacts_visibility.create() if installed
        # which sets user_id to creator if not already set
        partners = super().create(vals_list)
        
        # Post-process: update referral chain and salesperson assignment
        # This runs AFTER ox_own_contacts_visibility logic, so we can override if needed
        for partner in partners:
            # Mark click as converted if partner was created from referral link
            if referral_code:
                try:
                    # Find recent click for this referral code and mark as converted
                    click = self.env['referral.link.click'].sudo().search([
                        ('referral_code', '=', referral_code),
                        ('converted', '=', False)
                    ], order='click_date desc', limit=1)
                    if click:
                        click.mark_as_converted(partner.id)
                        _logger.info(f"[res.partner.create] Marked click {click.id} as converted for partner {partner.id}")
                except Exception as e:
                    _logger.warning(f"[res.partner.create] Could not mark click as converted: {str(e)}")
            
            # Process referral chain if referred_by_id is set
            if partner.referred_by_id:
                # Partner was referred via referral link
                referred_by = partner.referred_by_id

                _logger.info(
                    f"[res.partner.create] Processing referral chain for partner {partner.id}. "
                    f"referred_by: id={referred_by.id}, name={referred_by.name}, email={referred_by.email}, "
                    f"user_id={referred_by.user_id.id if referred_by.user_id else False}, "
                    f"user_id.share={referred_by.user_id.share if referred_by.user_id else 'N/A'}, "
                    f"user_id.active={referred_by.user_id.active if referred_by.user_id else 'N/A'}, "
                    f"referral_level={referred_by.referral_level}, "
                    f"is_doctor_1={referred_by.is_doctor_1}, "
                    f"is_salesperson_onboarded={referred_by.is_salesperson_onboarded}, "
                    f"referral_salesperson_id={referred_by.referral_salesperson_id.id if referred_by.referral_salesperson_id else False}"
                )

                # Check if referring partner IS an internal user (salesperson)
                # IMPORTANT: Check referred_by.user_ids (their OWN login), NOT referred_by.user_id (salesperson field)
                # A salesperson's own login should be an internal user (has base.group_user)
                user_group_id = self.env['ir.model.data']._xmlid_to_res_id('base.group_user')
                referred_by_own_user = referred_by.user_ids[:1] if referred_by.user_ids else False
                is_internal_user_referral = False
                salesperson_id = False

                if referred_by_own_user:
                    has_internal_group = user_group_id in referred_by_own_user.groups_id.ids
                    is_internal_user_referral = referred_by_own_user.active and has_internal_group
                    if is_internal_user_referral:
                        # The referring partner IS a salesperson - use their own user ID
                        salesperson_id = referred_by_own_user.id

                _logger.info(
                    f"[res.partner.create] is_internal_user_referral={is_internal_user_referral} "
                    f"(referred_by.user_ids={referred_by.user_ids.ids}, "
                    f"referred_by_own_user={referred_by_own_user.id if referred_by_own_user else False}, "
                    f"has_internal_group={has_internal_group if referred_by_own_user else 'N/A'}, "
                    f"salesperson_id={salesperson_id})"
                )

                # If not internal user referral, get salesperson from referral chain
                if not is_internal_user_referral:
                    # Referring partner is portal user (doctor) or has no user
                    # Try to get salesperson from referral chain
                    salesperson_id = (
                        referred_by.referral_salesperson_id.id if referred_by.referral_salesperson_id
                        else False
                    )

                if is_internal_user_referral:

                    # Check if partner being created is itself an internal user (has internal login)
                    # Internal users should NOT have is_salesperson_onboarded = True
                    # NOTE: Use partner.user_ids (partner's own login), NOT partner.user_id (salesperson field)
                    partner_own_user = partner.user_ids[:1] if partner.user_ids else False
                    user_group_id = self.env['ir.model.data']._xmlid_to_res_id('base.group_user')
                    is_partner_internal_user = False
                    if partner_own_user:
                        has_internal_group = user_group_id in partner_own_user.groups_id.ids
                        is_partner_internal_user = partner_own_user.active and has_internal_group

                    _logger.info(
                        f"[res.partner.create] referred_by_id context check: partner {partner.id}, "
                        f"partner_own_user={partner_own_user.id if partner_own_user else False}, "
                        f"is_partner_internal_user={is_partner_internal_user}"
                    )

                    # Only set is_salesperson_onboarded if partner is NOT an internal user
                    # Referral levels: 0=Salesperson, 1=Doctor 1, 2=Doctor 2/3/4, 999=Company
                    write_vals = {
                        'referral_level': 1,  # Doctor 1
                        'referral_salesperson_id': salesperson_id,  # Set to the internal user who referred them
                        'user_id': salesperson_id,  # Set to salesperson
                    }

                    if not is_partner_internal_user:
                        # Partner is a portal user (doctor) - can be Doctor 1
                        write_vals['is_salesperson_onboarded'] = True
                        write_vals['is_doctor_1'] = True
                    else:
                        # Partner is an internal user (salesperson) - cannot be Doctor 1
                        write_vals['is_salesperson_onboarded'] = False
                        write_vals['is_doctor_1'] = False

                    partner.write(write_vals)
                    _logger.info(
                        f"[res.partner.create] Partner {partner.id} set as Doctor 1 (level 1) "
                        f"(referred by internal user/salesperson {salesperson_id} - {referred_by_own_user.name}), "
                        f"referral_salesperson_id set to: {salesperson_id} ({referred_by_own_user.name})"
                    )
                elif salesperson_id and referred_by.referral_level == 1:
                    # Referred by Doctor 1 (level 1) - this is Doctor 2/3/4
                    # Assign to same salesperson
                    partner.write({
                        'is_doctor_referred': True,
                        'referral_level': 2,  # Doctor 2/3/4
                        'referral_salesperson_id': salesperson_id,
                        'user_id': salesperson_id,  # Set to salesperson
                    })
                    _logger.info(
                        f"[res.partner.create] Partner {partner.id} set as Doctor 2/3/4 (level 2) "
                        f"(referred by Doctor 1 {referred_by.id}), salesperson: {salesperson_id}"
                    )
                elif referred_by.referral_level == 2:
                    # Referred by Doctor 2/3/4 (level 1) - assign company property user
                    company_property_user_id = self.env['ir.config_parameter'].sudo().get_param(
                        'ox_doctor_referral_program.company_property_user_id', False
                    )
                    if company_property_user_id:
                        try:
                            company_property_user_id = int(company_property_user_id)
                            # Verify user exists and is active
                            company_user = self.env['res.users'].sudo().browse(company_property_user_id)
                            if company_user.exists() and company_user.active:
                                partner.write({
                                    'referral_type': 'company',
                                    'referral_level': 999,
                                    'referral_salesperson_id': False,
                                    'user_id': company_property_user_id,  # Assign company property user
                                })
                                _logger.info(
                                    f"[res.partner.create] Partner {partner.id} set as company referral "
                                    f"(referred by Doctor 2/3/4 {referred_by.id}), "
                                    f"assigned company property user: {company_property_user_id}"
                                )
                            else:
                                # User not found or inactive, fallback to no user
                                partner.write({
                                    'referral_type': 'company',
                                    'referral_level': 999,
                                    'referral_salesperson_id': False,
                                    'user_id': False,
                                })
                                _logger.warning(
                                    f"[res.partner.create] Company property user {company_property_user_id} not found or inactive. "
                                    f"Partner {partner.id} set without user assignment."
                                )
                        except (ValueError, TypeError):
                            # Invalid user ID format
                            partner.write({
                                'referral_type': 'company',
                                'referral_level': 999,
                                'referral_salesperson_id': False,
                                'user_id': False,
                            })
                            _logger.warning(
                                f"[res.partner.create] Invalid company property user ID format. "
                                f"Partner {partner.id} set without user assignment."
                            )
                    else:
                        # No company property user configured, fallback to no user
                        partner.write({
                            'referral_type': 'company',
                            'referral_level': 999,
                            'referral_salesperson_id': False,
                            'user_id': False,
                        })
                        _logger.info(
                            f"[res.partner.create] Partner {partner.id} set as company referral "
                            f"(referred by Doctor 2/3/4 {referred_by.id}), no company property user configured"
                        )
                else:
                    # Referred by level 2+ referrals - company referral without user
                    partner.write({
                        'referral_type': 'company',
                        'referral_level': 999,
                        'referral_salesperson_id': False,
                        'user_id': False,  # Clear salesperson field (company referral)
                    })
                    _logger.info(
                        f"[res.partner.create] Partner {partner.id} set as company referral "
                        f"(referred by {referred_by.id}, level {referred_by.referral_level}) - no user"
                    )
            
            # Also check if referral code was in session/context but referred_by_id wasn't set
            # This handles cases where partner is created but referred_by_id wasn't in vals
            elif referral_code and not partner.referred_by_id:
                referring_partner = self.get_partner_by_referral_code(referral_code)
                if referring_partner:
                    # Set referred_by_id and process referral chain
                    partner.write({'referred_by_id': referring_partner.id})
                    # Recursively process (will be handled by write method or next iteration)
                    referred_by = referring_partner

                    # Check if referring partner IS an internal user (salesperson)
                    # IMPORTANT: Check referred_by.user_ids (their OWN login), NOT referred_by.user_id (salesperson field)
                    user_group_id = self.env['ir.model.data']._xmlid_to_res_id('base.group_user')
                    referred_by_own_user = referred_by.user_ids[:1] if referred_by.user_ids else False
                    is_internal_user_referral = False
                    salesperson_id = False

                    if referred_by_own_user:
                        has_internal_group = user_group_id in referred_by_own_user.groups_id.ids
                        is_internal_user_referral = referred_by_own_user.active and has_internal_group
                        if is_internal_user_referral:
                            # The referring partner IS a salesperson - use their own user ID
                            salesperson_id = referred_by_own_user.id

                    # If not internal user referral, get salesperson from referral chain
                    if not is_internal_user_referral:
                        salesperson_id = (
                            referred_by.referral_salesperson_id.id if referred_by.referral_salesperson_id
                            else False
                        )

                    _logger.info(
                        f"[res.partner.create] Session referral processing for partner {partner.id}. "
                        f"referred_by: id={referred_by.id}, email={referred_by.email}, "
                        f"user_ids={referred_by.user_ids.ids}, "
                        f"referred_by_own_user={referred_by_own_user.id if referred_by_own_user else False}, "
                        f"is_internal_user_referral={is_internal_user_referral}, "
                        f"salesperson_id={salesperson_id}, "
                        f"referral_level={referred_by.referral_level}"
                    )

                    if is_internal_user_referral:

                        # Check if partner being created is itself an internal user (has internal login)
                        # NOTE: Use partner.user_ids (partner's own login), NOT partner.user_id (salesperson field)
                        partner_own_user = partner.user_ids[:1] if partner.user_ids else False
                        user_group_id = self.env['ir.model.data']._xmlid_to_res_id('base.group_user')
                        is_partner_internal_user = False
                        if partner_own_user:
                            has_internal_group = user_group_id in partner_own_user.groups_id.ids
                            is_partner_internal_user = partner_own_user.active and has_internal_group

                        _logger.info(
                            f"[res.partner.create] Session referral: partner {partner.id}, "
                            f"partner_own_user={partner_own_user.id if partner_own_user else False}, "
                            f"is_partner_internal_user={is_partner_internal_user}"
                        )

                        # Referral levels: 0=Salesperson, 1=Doctor 1, 2=Doctor 2/3/4, 999=Company
                        write_vals = {
                            'referral_level': 1,  # Doctor 1
                            'referral_salesperson_id': salesperson_id,
                            'user_id': salesperson_id,
                        }

                        if not is_partner_internal_user:
                            write_vals['is_salesperson_onboarded'] = True
                            write_vals['is_doctor_1'] = True
                        else:
                            write_vals['is_salesperson_onboarded'] = False
                            write_vals['is_doctor_1'] = False

                        partner.write(write_vals)
                        _logger.info(
                            f"[res.partner.create] Partner {partner.id} set as Doctor 1 (level 1) "
                            f"from session referral code {referral_code}, salesperson: {salesperson_id}"
                        )
                    elif salesperson_id and referred_by.referral_level == 1:
                        # Referred by Doctor 1 (level 1) - this is Doctor 2/3/4
                        partner.write({
                            'is_doctor_referred': True,
                            'referral_level': 2,  # Doctor 2/3/4
                            'referral_salesperson_id': salesperson_id,
                            'user_id': salesperson_id,
                        })
                        _logger.info(
                            f"[res.partner.create] Partner {partner.id} set as Doctor 2/3/4 (level 2) "
                            f"from session referral code {referral_code}, salesperson: {salesperson_id}"
                        )
                    elif referred_by.referral_level == 2:
                        # Referred by Doctor 2/3/4 (level 2) - assign company property user
                        company_property_user_id = self.get_company_property_user_id()
                        if company_property_user_id:
                            partner.write({
                                'referral_type': 'company',
                                'referral_level': 999,
                                'referral_salesperson_id': False,
                                'user_id': company_property_user_id,  # Assign company property user
                            })
                            _logger.info(
                                f"[res.partner.create] Partner {partner.id} set as company referral "
                                f"from session referral code {referral_code} (referred by Doctor 2/3/4 {referred_by.id}), "
                                f"assigned company property user: {company_property_user_id}"
                            )
                        else:
                            # No company property user configured
                            partner.write({
                                'referral_type': 'company',
                                'referral_level': 999,
                                'referral_salesperson_id': False,
                                'user_id': False,
                            })
                            _logger.info(
                                f"[res.partner.create] Partner {partner.id} set as company referral "
                                f"from session referral code {referral_code} (referred by Doctor 2/3/4 {referred_by.id}), "
                                f"no company property user configured"
                            )
                    else:
                        # Referred by level 3+ referrals - company referral without user
                        partner.write({
                            'referral_type': 'company',
                            'referral_level': 999,
                            'referral_salesperson_id': False,
                            'user_id': False,
                        })
                        _logger.info(
                            f"[res.partner.create] Partner {partner.id} set as company referral "
                            f"from session referral code {referral_code} (referred by level {referred_by.referral_level})"
                        )
            else:
                # No referral chain - manually created contact or direct signup
                # Check if manually created by a salesperson
                creator = self.env.user
                if (creator and creator.id != SUPERUSER_ID and 
                    creator.has_group('sales_team.group_sale_salesman')):
                    # If ox_own_contacts_visibility is installed, user_id is already set to creator
                    # We just need to set referral flags
                    
                    # Check if partner being created is itself an internal user (has internal login)
                    # Internal users should NOT have is_salesperson_onboarded = True
                    # NOTE: Use partner.user_ids (partner's own login), NOT partner.user_id (salesperson field)
                    partner_own_user = partner.user_ids[:1] if partner.user_ids else False
                    user_group_id = self.env['ir.model.data']._xmlid_to_res_id('base.group_user')
                    is_partner_internal_user = False
                    if partner_own_user:
                        has_internal_group = user_group_id in partner_own_user.groups_id.ids
                        is_partner_internal_user = partner_own_user.active and has_internal_group

                    _logger.info(
                        f"[res.partner.create] Manual creation: partner {partner.id}, "
                        f"partner_own_user={partner_own_user.id if partner_own_user else False}, "
                        f"is_partner_internal_user={is_partner_internal_user}"
                    )

                    # Referral levels: 0=Salesperson, 1=Doctor 1, 2=Doctor 2/3/4, 999=Company
                    write_vals = {
                        'referral_salesperson_id': creator.id,
                        'user_id': creator.id,  # Ensure it's set (may already be set by ox_own_contacts_visibility)
                        'referral_level': 1,  # Doctor 1 (manually created by salesperson)
                    }

                    if not is_partner_internal_user:
                        # Partner is a portal user (doctor) - can be Doctor 1
                        write_vals['is_salesperson_onboarded'] = True
                        write_vals['is_doctor_1'] = True
                    else:
                        # Partner is an internal user (salesperson) - cannot be Doctor 1
                        write_vals['is_salesperson_onboarded'] = False
                        write_vals['is_doctor_1'] = False

                    partner.write(write_vals)
                    _logger.info(
                        f"[res.partner.create] Partner {partner.id} manually created by salesperson {creator.id} (level 1)"
                    )
                else:
                    # Direct signup without referral link - assign company property user
                    company_property_user_id = self.get_company_property_user_id()
                    if company_property_user_id:
                        partner.write({
                            'referral_type': 'company',
                            'referral_level': 999,
                            'referral_salesperson_id': False,
                            'user_id': company_property_user_id,  # Assign company property user
                        })
                        _logger.info(
                            f"[res.partner.create] Partner {partner.id} signed up directly without referral link, "
                            f"assigned company property user: {company_property_user_id}"
                        )
                    else:
                        # No company property user configured - let other modules handle user_id
                        _logger.info(
                            f"[res.partner.create] Partner {partner.id} signed up directly without referral link, "
                            f"no company property user configured"
                        )
                    # If ox_own_contacts_visibility is installed, it may handle user_id assignment
                    # We just ensure referral_code is set (already done above)
        
        return partners

    def write(self, vals):
        """Update referral chain when referred_by_id changes
        Also fix is_salesperson_onboarded when user_id changes
        """
        # Log incoming vals for debugging
        _logger.info(
            f"[res.partner.write] === START === Partner IDs: {self.ids}, "
            f"incoming vals keys: {list(vals.keys())}, "
            f"user_id in vals: {vals.get('user_id', 'NOT SET')}, "
            f"referral_salesperson_id in vals: {vals.get('referral_salesperson_id', 'NOT SET')}"
        )

        # Fix is_salesperson_onboarded if user_id is being changed
        # Only clear flags if the PARTNER ITSELF is an internal user (has an internal res.users login)
        # NOTE: user_id is the SALESPERSON field — a portal doctor having user_id pointing to an
        # internal salesperson is normal and should NOT clear is_salesperson_onboarded/is_doctor_1.
        # We only clear these flags when the partner's OWN user (user_ids) is internal.
        if 'user_id' in vals:
            new_user_id = vals.get('user_id')
            if not new_user_id:
                # user_id being cleared - also clear referral flags
                if 'is_salesperson_onboarded' not in vals:
                    vals['is_salesperson_onboarded'] = False
                if 'is_doctor_1' not in vals:
                    vals['is_doctor_1'] = False
            else:
                # Only block flags if the partner's own login user is the same internal user
                # (meaning the partner IS the salesperson, not just assigned to one)
                user_group_id = self.env['ir.model.data']._xmlid_to_res_id('base.group_user')
                for partner in self:
                    partner_own_user = partner.user_ids[:1] if partner.user_ids else False
                    if partner_own_user and partner_own_user.id == new_user_id:
                        # Partner's own user is being set as salesperson — they ARE the internal user
                        # Use direct group check instead of share field (share is computed and may be stale)
                        has_internal_group = user_group_id in partner_own_user.groups_id.ids
                        _logger.info(
                            f"[res.partner.write] CHECK 1: partner {partner.id}, partner_own_user {partner_own_user.id}, "
                            f"new_user_id={new_user_id}, groups_id={partner_own_user.groups_id.ids}, "
                            f"has_internal_group={has_internal_group}, share={partner_own_user.share}"
                        )
                        if partner_own_user.exists() and partner_own_user.active and has_internal_group:
                            vals['is_salesperson_onboarded'] = False
                            vals['is_doctor_1'] = False
                            _logger.info(
                                f"[res.partner.write] Fixed is_salesperson_onboarded=False for partner {partner.id} "
                                f"because partner's own user (user_id={new_user_id}) is internal (has base.group_user)"
                            )
        
        # Also check existing partners — only fix flags if the partner's OWN user is internal
        # (not just because user_id/salesperson field points to an internal user)
        if 'is_salesperson_onboarded' not in vals and 'is_doctor_1' not in vals:
            for partner in self:
                partner_own_user = partner.user_ids[:1] if partner.user_ids else False
                _logger.info(
                    f"[res.partner.write] SAFETY CHECK: partner {partner.id}, "
                    f"user_ids: {partner.user_ids.ids}, "
                    f"partner_own_user: {partner_own_user.id if partner_own_user else False}, "
                    f"vals keys: {list(vals.keys())}"
                )
                if partner_own_user:
                    # Check groups_id to determine if internal (has base.group_user)
                    user_group_id = self.env['ir.model.data']._xmlid_to_res_id('base.group_user')
                    has_internal_group = user_group_id in partner_own_user.groups_id.ids
                    _logger.info(
                        f"[res.partner.write] SAFETY CHECK: partner_own_user {partner_own_user.id} ({partner_own_user.login}), "
                        f"active={partner_own_user.active}, share={partner_own_user.share}, "
                        f"groups_id={partner_own_user.groups_id.ids}, "
                        f"has_internal_group (base.group_user={user_group_id}): {has_internal_group}"
                    )
                    # Use direct group check instead of share field (share is computed and may be stale)
                    if partner_own_user.active and has_internal_group:
                        # Partner's own login is an internal user — they cannot be doctor 1
                        if partner.is_salesperson_onboarded:
                            partner.write({
                                'is_salesperson_onboarded': False,
                                'is_doctor_1': False,
                            })
                            _logger.info(
                                f"[res.partner.write] Fixed is_salesperson_onboarded=False for partner {partner.id} "
                                f"because partner's own user ({partner_own_user.id}) is internal (has base.group_user)"
                            )
        
        if 'referred_by_id' in vals:
            for partner in self:
                if vals['referred_by_id']:
                    referred_by = self.browse(vals['referred_by_id'])

                    # Check if referring partner IS an internal user (salesperson)
                    # IMPORTANT: Check referred_by.user_ids (their OWN login), NOT referred_by.user_id (salesperson field)
                    user_group_id = self.env['ir.model.data']._xmlid_to_res_id('base.group_user')
                    referred_by_own_user = referred_by.user_ids[:1] if referred_by.user_ids else False
                    is_internal_user_referral = False
                    salesperson_id = False

                    if referred_by_own_user:
                        has_internal_group = user_group_id in referred_by_own_user.groups_id.ids
                        is_internal_user_referral = referred_by_own_user.active and has_internal_group
                        if is_internal_user_referral:
                            # The referring partner IS a salesperson - use their own user ID
                            salesperson_id = referred_by_own_user.id

                    # If not internal user referral, get salesperson from referral chain
                    if not is_internal_user_referral:
                        salesperson_id = (
                            referred_by.referral_salesperson_id.id if referred_by.referral_salesperson_id
                            else False
                        )

                    _logger.info(
                        f"[res.partner.write] referred_by_id processing: referred_by={referred_by.id}, "
                        f"user_ids={referred_by.user_ids.ids}, referred_by_own_user={referred_by_own_user.id if referred_by_own_user else False}, "
                        f"is_internal_user_referral={is_internal_user_referral}, salesperson_id={salesperson_id}"
                    )

                    if is_internal_user_referral:
                        # Referred by internal user (salesperson) - Doctor 1
                        # Check if partner being updated is itself an internal user (has internal login)
                        # Internal users should NOT have is_salesperson_onboarded = True
                        # NOTE: Use partner.user_ids (partner's own login), NOT partner.user_id (salesperson field)
                        partner_own_user = partner.user_ids[:1] if partner.user_ids else False
                        user_group_id = self.env['ir.model.data']._xmlid_to_res_id('base.group_user')
                        is_partner_internal_user = False
                        if partner_own_user:
                            has_internal_group = user_group_id in partner_own_user.groups_id.ids
                            is_partner_internal_user = partner_own_user.active and has_internal_group

                        _logger.info(
                            f"[res.partner.write] referred_by_id check: partner {partner.id}, "
                            f"partner_own_user={partner_own_user.id if partner_own_user else False}, "
                            f"is_partner_internal_user={is_partner_internal_user}"
                        )

                        # Referral levels: 0=Salesperson, 1=Doctor 1, 2=Doctor 2/3/4, 999=Company
                        vals['referral_level'] = 1  # Doctor 1
                        vals['referral_salesperson_id'] = salesperson_id
                        vals['user_id'] = salesperson_id

                        if not is_partner_internal_user:
                            # Partner is a portal user (doctor) - can be Doctor 1
                            vals['is_salesperson_onboarded'] = True
                            vals['is_doctor_1'] = True
                        else:
                            # Partner is an internal user (salesperson) - cannot be Doctor 1
                            vals['is_salesperson_onboarded'] = False
                            vals['is_doctor_1'] = False
                    elif salesperson_id and referred_by.referral_level == 1:
                        # Referred by Doctor 1 (level 1) - this is Doctor 2/3/4
                        vals['referral_salesperson_id'] = salesperson_id
                        vals['user_id'] = salesperson_id  # Set native salesperson field
                        vals['referral_level'] = 2  # Doctor 2/3/4
                        vals['is_doctor_referred'] = True
                    elif referred_by.referral_level == 2:
                        # Referred by Doctor 2/3/4 (level 2) - assign company property user
                        company_property_user_id = self.get_company_property_user_id()
                        vals['referral_type'] = 'company'
                        vals['referral_level'] = 999
                        vals['referral_salesperson_id'] = False
                        vals['user_id'] = company_property_user_id if company_property_user_id else False
                    else:
                        # Referred by level 3+ referrals - company referral without user
                        vals['referral_type'] = 'company'
                        vals['referral_level'] = 999
                        vals['referral_salesperson_id'] = False
                        vals['user_id'] = False

        # Log final vals before calling super().write()
        _logger.info(
            f"[res.partner.write] === BEFORE SUPER === Partner IDs: {self.ids}, "
            f"final vals keys: {list(vals.keys())}, "
            f"user_id: {vals.get('user_id', 'NOT SET')}, "
            f"referral_salesperson_id: {vals.get('referral_salesperson_id', 'NOT SET')}, "
            f"is_salesperson_onboarded: {vals.get('is_salesperson_onboarded', 'NOT SET')}, "
            f"is_doctor_1: {vals.get('is_doctor_1', 'NOT SET')}"
        )

        result = super().write(vals)

        # Log state after write
        for partner in self:
            _logger.info(
                f"[res.partner.write] === AFTER SUPER === Partner {partner.id}: "
                f"user_id={partner.user_id.id if partner.user_id else False}, "
                f"referral_salesperson_id={partner.referral_salesperson_id.id if partner.referral_salesperson_id else False}, "
                f"is_salesperson_onboarded={partner.is_salesperson_onboarded}, "
                f"is_doctor_1={partner.is_doctor_1}"
            )

        return result

    @api.model
    def get_company_property_user_id(self):
        """Get company property user ID from config parameter
        
        Returns:
            int or False: User ID if configured and valid, False otherwise
        """
        company_property_user_id = self.env['ir.config_parameter'].sudo().get_param(
            'ox_doctor_referral_program.company_property_user_id', False
        )
        if company_property_user_id:
            try:
                company_property_user_id = int(company_property_user_id)
                # Verify user exists and is active
                company_user = self.env['res.users'].sudo().browse(company_property_user_id)
                if company_user.exists() and company_user.active:
                    return company_property_user_id
                else:
                    _logger.warning(
                        f"[res.partner.get_company_property_user_id] Company property user {company_property_user_id} "
                        f"not found or inactive."
                    )
            except (ValueError, TypeError):
                _logger.warning(
                    f"[res.partner.get_company_property_user_id] Invalid company property user ID format: {company_property_user_id}"
                )
        return False
    
    @api.model
    def get_partner_by_referral_code(self, code):
        """Get partner by referral code"""
        return self.search([('referral_code', '=', code)], limit=1)
    
    @api.model
    def fix_internal_user_referral_flags(self):
        """Fix is_salesperson_onboarded and is_doctor_1 flags for internal users

        Internal users (salespersons) should never have:
        - is_salesperson_onboarded = True
        - is_doctor_1 = True

        This method fixes all existing incorrect records.

        NOTE: An internal user is determined by checking the partner's OWN login (user_ids),
              not the salesperson field (user_id). A partner is internal if their user_ids
              contains a user with base.group_user group.
        """
        # Find all partners with is_salesperson_onboarded = True
        incorrect_partners = self.search([
            ('is_salesperson_onboarded', '=', True),
        ])

        user_group_id = self.env['ir.model.data']._xmlid_to_res_id('base.group_user')
        fixed_count = 0
        for partner in incorrect_partners:
            # Check if partner's OWN login (user_ids) is internal user
            partner_own_user = partner.user_ids[:1] if partner.user_ids else False
            is_internal_user = False
            if partner_own_user:
                has_internal_group = user_group_id in partner_own_user.groups_id.ids
                is_internal_user = partner_own_user.active and has_internal_group

            if is_internal_user:
                partner.write({
                    'is_salesperson_onboarded': False,
                    'is_doctor_1': False,
                })
                fixed_count += 1
                _logger.info(
                    f"[res.partner.fix_internal_user_referral_flags] Fixed partner {partner.id} "
                    f"({partner.name}) - partner's own user={partner_own_user.id} ({partner_own_user.login}) is internal"
                )
        
        _logger.info(
            f"[res.partner.fix_internal_user_referral_flags] Fixed {fixed_count} partner(s) with incorrect flags"
        )
        return {
            'fixed_count': fixed_count,
            'message': f'Fixed {fixed_count} partner(s) with incorrect referral flags'
        }
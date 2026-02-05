# -*- coding: utf-8 -*-

import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Try to import ox_partner_npi controller (if installed)
try:
    from odoo.addons.ox_partner_npi.controllers.main import AuthSignupHomeNPI
    HAS_NPI_MODULE = True
except ImportError:
    # Fallback to standard auth_signup if NPI module not installed
    from odoo.addons.auth_signup.controllers.main import AuthSignupHome
    AuthSignupHomeNPI = AuthSignupHome
    HAS_NPI_MODULE = False


class ReferralSignupController(AuthSignupHomeNPI):
    """Extend signup to handle referral codes
    Works with both standard signup and ox_partner_npi signup flow
    """

    def get_auth_signup_qcontext(self):
        """Override to add referral_code to template context"""
        qcontext = super().get_auth_signup_qcontext()

        # Get referral code from URL params, form data, or session
        referral_code = (
            request.params.get('ref') or
            request.params.get('referral_code') or
            request.session.get('referral_code')
        )

        if referral_code:
            qcontext['referral_code'] = referral_code
            # Store in session for multi-step flows
            request.session['referral_code'] = referral_code
            _logger.info(f"[referral.signup.get_auth_signup_qcontext] Added referral_code to qcontext: {referral_code}")

        return qcontext

    @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False)
    def web_auth_signup(self, *args, **kw):
        """Handle signup with referral code"""
        referral_code = kw.get('ref') or kw.get('referral_code') or request.params.get('ref')

        _logger.info(
            f"[referral.signup.web_auth_signup] Called. ref from kw: {kw.get('ref')}, "
            f"referral_code from kw: {kw.get('referral_code')}, "
            f"ref from params: {request.params.get('ref')}, "
            f"session referral_code before: {request.session.get('referral_code')}, "
            f"session ID: {getattr(request.session, 'sid', 'N/A')}"
        )

        if referral_code:
            # Store referral code in session for later use
            request.session['referral_code'] = referral_code
            _logger.info(f"[referral.signup.web_auth_signup] Stored referral code in session: {referral_code}")
        else:
            _logger.info("[referral.signup.web_auth_signup] No referral code found in request")

        return super().web_auth_signup(*args, **kw)

    def _prepare_signup_values(self, qcontext):
        """Override to capture referral_code from form and store in session"""
        values = super()._prepare_signup_values(qcontext)

        # Get referral code from form, qcontext, or session
        referral_code = (
            qcontext.get('referral_code') or
            request.params.get('referral_code') or
            request.params.get('ref') or
            request.session.get('referral_code')
        )

        if referral_code:
            # Store in session so it's available during partner creation
            request.session['referral_code'] = referral_code
            _logger.info(f"[referral.signup._prepare_signup_values] Captured referral_code: {referral_code}")

        return values

    def _proceed_with_invitation_flow(self, qcontext, signup_name, npi_number, npi_data):
        """Override to include referral code in signup_data"""
        # Get referral code from session or params
        referral_code = request.session.get('referral_code') or request.params.get('ref')

        _logger.info(
            f"[referral.signup._proceed_with_invitation_flow] Called. "
            f"referral_code from session: {request.session.get('referral_code')}, "
            f"referral_code from params: {request.params.get('ref')}, "
            f"resolved referral_code: {referral_code}, "
            f"session ID: {getattr(request.session, 'sid', 'N/A')}"
        )

        # Call parent method
        result = super()._proceed_with_invitation_flow(qcontext, signup_name, npi_number, npi_data)

        # Add referral code to signup_data if present
        if referral_code and 'signup_data' in request.session:
            if not isinstance(request.session['signup_data'], dict):
                request.session['signup_data'] = {}
            request.session['signup_data']['referral_code'] = referral_code
            _logger.info(
                f"[referral.signup._proceed_with_invitation_flow] Stored referral code in signup_data: {referral_code}, "
                f"signup_data keys: {list(request.session['signup_data'].keys())}"
            )
        elif referral_code:
            _logger.warning(
                f"[referral.signup._proceed_with_invitation_flow] referral_code={referral_code} but "
                f"'signup_data' not in session! Session keys: {list(request.session.keys())}"
            )
        else:
            _logger.info("[referral.signup._proceed_with_invitation_flow] No referral code to store")

        return result
    
    def _complete_signup(self, signup_data):
        """Override to add referral processing after partner creation

        IMPORTANT: Capture referral_code BEFORE calling super() because:
        1. super()._complete_signup() calls request.session.authenticate() which rotates
           the session, destroying request.session['referral_code']
        2. super()._complete_signup() pops 'signup_data' from session
        3. res.partner.create() inside super() needs the referral_code via session/context
           since _signup_with_values() is bypassed in the NPI multi-step flow
        """
        # Capture referral code BEFORE super() destroys session data
        _logger.info(
            f"[referral.signup._complete_signup] === START === "
            f"signup_data keys: {list(signup_data.keys())}, "
            f"signup_data.referral_code: {signup_data.get('referral_code')}, "
            f"session.referral_code: {request.session.get('referral_code')}, "
            f"session signup_data.referral_code: {request.session.get('signup_data', {}).get('referral_code') if isinstance(request.session.get('signup_data'), dict) else 'N/A'}, "
            f"request.params.ref: {request.params.get('ref')}, "
            f"session ID: {getattr(request.session, 'sid', 'N/A')}, "
            f"session keys: {list(request.session.keys())}"
        )

        referral_code = (
            signup_data.get('referral_code') or
            request.session.get('referral_code') or
            request.params.get('ref')
        )

        _logger.info(
            f"[referral.signup._complete_signup] Resolved referral_code: {referral_code}"
        )

        if referral_code:
            _logger.info(
                f"[referral.signup._complete_signup] Captured referral code before super(): {referral_code}"
            )
            # Store in signup_data so it persists
            signup_data['referral_code'] = referral_code
            # Ensure it's in session's signup_data (for res.partner.create() to read)
            if 'signup_data' in request.session and isinstance(request.session['signup_data'], dict):
                request.session['signup_data']['referral_code'] = referral_code
            # Ensure standalone session key exists (backup for res.partner.create())
            request.session['referral_code'] = referral_code
            _logger.info(
                f"[referral.signup._complete_signup] Referral code stored in all locations. "
                f"Calling super()._complete_signup()..."
            )
        else:
            _logger.info(
                "[referral.signup._complete_signup] No referral code found. Calling super()._complete_signup()..."
            )

        # Call parent to complete signup (creates user/partner, saves NPI, terms, etc.)
        # NOTE: super() calls res.users.signup() → res.partner.create() which reads
        # referral_code from request.session['referral_code'] or env.context['referral_code'].
        # After that, super() calls request.session.authenticate() which rotates the session.
        result = super()._complete_signup(signup_data)

        # After super(), session has been rotated by authenticate() — referral_code in
        # session is gone. But we saved it in a local variable above.
        _logger.info(
            f"[referral.signup._complete_signup] super() returned. "
            f"result type: {type(result).__name__}, "
            f"session ID after: {getattr(request.session, 'sid', 'N/A')}, "
            f"session.referral_code after: {request.session.get('referral_code')}, "
            f"local referral_code: {referral_code}"
        )

        # Find the newly created partner by login email (session.user may not work after rotation)
        partner = None
        login_email = signup_data.get('login')
        _logger.info(
            f"[referral.signup._complete_signup] Looking up partner by login_email: {login_email}"
        )
        if login_email:
            user = request.env['res.users'].sudo().search([('login', '=', login_email)], limit=1)
            if user and user.partner_id:
                partner = user.partner_id.sudo()
                _logger.info(
                    f"[referral.signup._complete_signup] Found partner {partner.id} ({partner.email}) by login search. "
                    f"referred_by_id: {partner.referred_by_id.id if partner.referred_by_id else False}, "
                    f"user_id: {partner.user_id.id if partner.user_id else False}, "
                    f"referral_level: {partner.referral_level}, "
                    f"is_salesperson_onboarded: {partner.is_salesperson_onboarded}, "
                    f"is_doctor_1: {partner.is_doctor_1}"
                )
            else:
                _logger.warning(
                    f"[referral.signup._complete_signup] No user found by login: {login_email}"
                )

        # Fallback: try request.env.user
        if not partner:
            user = request.env.user
            _logger.info(
                f"[referral.signup._complete_signup] Fallback: request.env.user = {user}, uid={getattr(user, 'id', 'N/A')}"
            )
            if user and user.partner_id:
                partner = user.partner_id.sudo()
                _logger.info(
                    f"[referral.signup._complete_signup] Fallback found partner {partner.id} ({partner.email})"
                )

        if not partner:
            _logger.warning(
                f"[referral.signup._complete_signup] Could not find partner after signup for {login_email}"
            )
            return result

        if referral_code:
            try:
                # Only process if partner doesn't already have referral chain set
                # (res.partner.create() may have already processed it)
                if not partner.referred_by_id:
                    # Find referring partner
                    referring_partner = request.env['res.partner'].sudo().get_partner_by_referral_code(referral_code)

                    if referring_partner:
                        # Check if referring partner IS an internal user (salesperson)
                        # IMPORTANT: Check referring_partner.user_ids (their OWN login), NOT referring_partner.user_id (salesperson field)
                        user_group_id = request.env['ir.model.data'].sudo()._xmlid_to_res_id('base.group_user')
                        referring_partner_own_user = referring_partner.user_ids[:1] if referring_partner.user_ids else False
                        is_internal_user_referral = False
                        salesperson_id = False

                        if referring_partner_own_user:
                            has_internal_group = user_group_id in referring_partner_own_user.groups_id.ids
                            is_internal_user_referral = referring_partner_own_user.active and has_internal_group
                            if is_internal_user_referral:
                                # The referring partner IS a salesperson - use their own user ID
                                salesperson_id = referring_partner_own_user.id

                        # If not internal user referral, get salesperson from referral chain
                        if not is_internal_user_referral:
                            salesperson_id = (
                                referring_partner.referral_salesperson_id.id if referring_partner.referral_salesperson_id
                                else False
                            )

                        _logger.info(
                            f"[referral.signup._complete_signup] Referring partner check: "
                            f"referring_partner={referring_partner.id}, user_ids={referring_partner.user_ids.ids}, "
                            f"referring_partner_own_user={referring_partner_own_user.id if referring_partner_own_user else False}, "
                            f"is_internal_user_referral={is_internal_user_referral}, salesperson_id={salesperson_id}"
                        )

                        if is_internal_user_referral:
                            # Referred by salesperson (internal user) directly - this is Doctor 1

                            # Check if partner is itself an internal user
                            # NOTE: Use partner.user_ids (partner's own login), NOT partner.user_id (salesperson field)
                            partner_own_user = partner.user_ids[:1] if partner.user_ids else False
                            is_partner_internal_user = False
                            if partner_own_user:
                                has_internal_group = user_group_id in partner_own_user.groups_id.ids
                                is_partner_internal_user = partner_own_user.active and has_internal_group

                            _logger.info(
                                f"[referral.signup._complete_signup] BEFORE WRITE - Partner {partner.id}: "
                                f"user_id={partner.user_id.id if partner.user_id else False}, "
                                f"referral_salesperson_id={partner.referral_salesperson_id.id if partner.referral_salesperson_id else False}, "
                                f"user_ids={partner.user_ids.ids}, "
                                f"partner_own_user={partner_own_user.id if partner_own_user else False}, "
                                f"is_partner_internal_user={is_partner_internal_user}, "
                                f"salesperson_id to set={salesperson_id}"
                            )

                            # Referral levels: 0=Salesperson, 1=Doctor 1, 2=Doctor 2/3/4, 999=Company
                            write_vals = {
                                'referred_by_id': referring_partner.id,
                                'referral_salesperson_id': salesperson_id,
                                'user_id': salesperson_id,
                                'referral_level': 1,  # Doctor 1
                            }

                            if not is_partner_internal_user:
                                write_vals['is_salesperson_onboarded'] = True
                                write_vals['is_doctor_1'] = True
                            else:
                                write_vals['is_salesperson_onboarded'] = False
                                write_vals['is_doctor_1'] = False

                            _logger.info(
                                f"[referral.signup._complete_signup] Calling partner.write() with vals: {write_vals}"
                            )
                            partner.write(write_vals)

                            # Re-read partner to verify write succeeded
                            partner.invalidate_recordset()
                            _logger.info(
                                f"[referral.signup._complete_signup] AFTER WRITE - Partner {partner.id}: "
                                f"user_id={partner.user_id.id if partner.user_id else False} (expected {salesperson_id}), "
                                f"referral_salesperson_id={partner.referral_salesperson_id.id if partner.referral_salesperson_id else False} (expected {salesperson_id}), "
                                f"referred_by_id={partner.referred_by_id.id if partner.referred_by_id else False}, "
                                f"referral_level={partner.referral_level}, "
                                f"is_salesperson_onboarded={partner.is_salesperson_onboarded}, "
                                f"is_doctor_1={partner.is_doctor_1}"
                            )
                        elif salesperson_id and referring_partner.referral_level == 1:
                            # Referred by Doctor 1 (level 1) - this is Doctor 2/3/4
                            partner.write({
                                'referred_by_id': referring_partner.id,
                                'referral_salesperson_id': salesperson_id,
                                'user_id': salesperson_id,
                                'is_doctor_referred': True,
                                'referral_level': 2,  # Doctor 2/3/4
                            })
                            _logger.info(
                                f"[referral.signup._complete_signup] Partner {partner.id} set as Doctor 2/3/4 (level 2) "
                                f"(referred by Doctor 1 {referring_partner.id}), salesperson: {salesperson_id}"
                            )
                        elif referring_partner.referral_level == 2:
                            # Referred by Doctor 2/3/4 (level 1) - assign company property user
                            company_property_user_id = request.env['ir.config_parameter'].sudo().get_param(
                                'ox_doctor_referral_program.company_property_user_id', False
                            )
                            if company_property_user_id:
                                try:
                                    company_property_user_id = int(company_property_user_id)
                                    company_user = request.env['res.users'].sudo().browse(company_property_user_id)
                                    if company_user.exists() and company_user.active:
                                        partner.write({
                                            'referred_by_id': referring_partner.id,
                                            'referral_type': 'company',
                                            'referral_level': 999,
                                            'referral_salesperson_id': False,
                                            'user_id': company_property_user_id,
                                        })
                                        _logger.info(
                                            f"[referral.signup._complete_signup] Partner {partner.id} set as company referral "
                                            f"(referred by Doctor 2/3/4 {referring_partner.id}), "
                                            f"assigned company property user: {company_property_user_id}"
                                        )
                                    else:
                                        partner.write({
                                            'referred_by_id': referring_partner.id,
                                            'referral_type': 'company',
                                            'referral_level': 999,
                                            'referral_salesperson_id': False,
                                            'user_id': False,
                                        })
                                        _logger.warning(
                                            f"[referral.signup._complete_signup] Company property user {company_property_user_id} "
                                            f"not found or inactive. Partner {partner.id} set without user assignment."
                                        )
                                except (ValueError, TypeError):
                                    partner.write({
                                        'referred_by_id': referring_partner.id,
                                        'referral_type': 'company',
                                        'referral_level': 999,
                                        'referral_salesperson_id': False,
                                        'user_id': False,
                                    })
                                    _logger.warning(
                                        f"[referral.signup._complete_signup] Invalid company property user ID format. "
                                        f"Partner {partner.id} set without user assignment."
                                    )
                            else:
                                partner.write({
                                    'referred_by_id': referring_partner.id,
                                    'referral_type': 'company',
                                    'referral_level': 999,
                                    'referral_salesperson_id': False,
                                    'user_id': False,
                                })
                                _logger.info(
                                    f"[referral.signup._complete_signup] Partner {partner.id} set as company referral "
                                    f"(referred by Doctor 2/3/4 {referring_partner.id}), no company property user configured"
                                )
                        else:
                            # Referred by level 2+ referrals - company referral without user
                            partner.write({
                                'referred_by_id': referring_partner.id,
                                'referral_type': 'company',
                                'referral_level': 999,
                                'referral_salesperson_id': False,
                                'user_id': False,
                            })
                            _logger.info(
                                f"[referral.signup._complete_signup] Partner {partner.id} set as company referral "
                                f"(referred by {referring_partner.id}, level {referring_partner.referral_level}) - no user"
                            )

                        _logger.info(
                            f"[referral.signup._complete_signup] Partner {partner.id} registered via referral code {referral_code} "
                            f"from partner {referring_partner.id}. "
                            f"Salesperson: {partner.referral_salesperson_id.id if partner.referral_salesperson_id else 'None'}, "
                            f"Level: {partner.referral_level}, "
                            f"Is Doctor 1: {partner.is_doctor_1}"
                        )
                    else:
                        _logger.warning(
                            f"[referral.signup._complete_signup] Invalid referral code: {referral_code}"
                        )
                else:
                    _logger.info(
                        f"[referral.signup._complete_signup] Partner {partner.id} already has referral chain "
                        f"(referred_by_id={partner.referred_by_id.id}), skipping duplicate processing"
                    )

                # Clear referral code from session after processing
                request.session.pop('referral_code', None)
            except Exception as e:
                _logger.error(
                    f"[referral.signup._complete_signup] Error processing referral code {referral_code}: {str(e)}",
                    exc_info=True
                )
        elif partner:
            # No referral code - direct signup without referral link
            # Assign company property user if configured
            if not partner.user_id and not partner.referred_by_id:
                company_property_user_id = request.env['ir.config_parameter'].sudo().get_param(
                    'ox_doctor_referral_program.company_property_user_id', False
                )
                if company_property_user_id:
                    try:
                        company_property_user_id = int(company_property_user_id)
                        company_user = request.env['res.users'].sudo().browse(company_property_user_id)
                        if company_user.exists() and company_user.active:
                            partner.write({
                                'referral_type': 'company',
                                'referral_level': 999,
                                'referral_salesperson_id': False,
                                'user_id': company_property_user_id,
                            })
                            _logger.info(
                                f"[referral.signup._complete_signup] Partner {partner.id} signed up directly "
                                f"without referral link, assigned company property user: {company_property_user_id}"
                            )
                        else:
                            _logger.warning(
                                f"[referral.signup._complete_signup] Company property user {company_property_user_id} "
                                f"not found or inactive."
                            )
                    except (ValueError, TypeError):
                        _logger.warning(
                            f"[referral.signup._complete_signup] Invalid company property user ID format."
                        )
                else:
                    _logger.info(
                        f"[referral.signup._complete_signup] Partner {partner.id} signed up directly "
                        f"without referral link, no company property user configured"
                    )

        return result
    
    def _signup_with_values(self, token, values):
        """Process signup with referral code (for standard signup flow)"""
        referral_code = request.session.get('referral_code') or request.params.get('ref')
        
        # Store referral code in context so res.partner.create() can access it
        if referral_code:
            request.session['referral_code'] = referral_code
            self = self.with_context(referral_code=referral_code)
            _logger.info(f"[referral.signup._signup_with_values] Processing referral code: {referral_code}")
        
        # Call parent signup (creates user and partner, then authenticates)
        result = super()._signup_with_values(token, values)
        
        # Process referral after signup and authentication completes
        # Note: Referral processing also happens in res.partner.create() method
        # This is a backup in case partner was created before authentication
        
        # Get the newly created user (from authenticated session)
        user = request.env.user
        if user and user.partner_id:
            partner = user.partner_id.sudo()
            
            if referral_code:
                try:
                    # Only process if partner doesn't already have referral chain set
                    if not partner.referred_by_id:
                        # Find referring partner
                        referring_partner = request.env['res.partner'].sudo().get_partner_by_referral_code(referral_code)
                        
                        if referring_partner:
                            # Check if referring partner IS an internal user (salesperson)
                            # IMPORTANT: Check referring_partner.user_ids (their OWN login), NOT referring_partner.user_id (salesperson field)
                            user_group_id = request.env['ir.model.data'].sudo()._xmlid_to_res_id('base.group_user')
                            referring_partner_own_user = referring_partner.user_ids[:1] if referring_partner.user_ids else False
                            is_internal_user_referral = False
                            salesperson_id = False

                            if referring_partner_own_user:
                                has_internal_group = user_group_id in referring_partner_own_user.groups_id.ids
                                is_internal_user_referral = referring_partner_own_user.active and has_internal_group
                                if is_internal_user_referral:
                                    # The referring partner IS a salesperson - use their own user ID
                                    salesperson_id = referring_partner_own_user.id

                            # If not internal user referral, get salesperson from referral chain
                            if not is_internal_user_referral:
                                salesperson_id = (
                                    referring_partner.referral_salesperson_id.id if referring_partner.referral_salesperson_id
                                    else False
                                )

                            _logger.info(
                                f"[referral.signup._signup_with_values] Referring partner check: "
                                f"referring_partner={referring_partner.id}, user_ids={referring_partner.user_ids.ids}, "
                                f"referring_partner_own_user={referring_partner_own_user.id if referring_partner_own_user else False}, "
                                f"is_internal_user_referral={is_internal_user_referral}, salesperson_id={salesperson_id}"
                            )

                            if is_internal_user_referral:
                                # Referred by salesperson (internal user) directly - this is Doctor 1

                                # Check if partner being created is itself an internal user (salesperson)
                                # Internal users should NOT have is_salesperson_onboarded = True
                                # NOTE: Use partner.user_ids (partner's own login), NOT partner.user_id (salesperson field)
                                partner_own_user = partner.user_ids[:1] if partner.user_ids else False
                                is_partner_internal_user = False
                                if partner_own_user:
                                    has_internal_group = user_group_id in partner_own_user.groups_id.ids
                                    is_partner_internal_user = partner_own_user.active and has_internal_group

                                _logger.info(
                                    f"[referral.signup._signup_with_values] BEFORE WRITE - Partner {partner.id}: "
                                    f"user_id={partner.user_id.id if partner.user_id else False}, "
                                    f"referral_salesperson_id={partner.referral_salesperson_id.id if partner.referral_salesperson_id else False}, "
                                    f"user_ids={partner.user_ids.ids}, "
                                    f"partner_own_user={partner_own_user.id if partner_own_user else False}, "
                                    f"is_partner_internal_user={is_partner_internal_user}, "
                                    f"salesperson_id to set={salesperson_id}"
                                )

                                # Referral levels: 0=Salesperson, 1=Doctor 1, 2=Doctor 2/3/4, 999=Company
                                write_vals = {
                                    'referred_by_id': referring_partner.id,
                                    'referral_salesperson_id': salesperson_id,  # Set to the internal user who referred them
                                    'user_id': salesperson_id,
                                    'referral_level': 1,  # Doctor 1
                                }

                                if not is_partner_internal_user:
                                    # Partner is a portal user (doctor) - can be Doctor 1
                                    write_vals['is_salesperson_onboarded'] = True
                                    write_vals['is_doctor_1'] = True
                                else:
                                    # Partner is an internal user (salesperson) - cannot be Doctor 1
                                    write_vals['is_salesperson_onboarded'] = False
                                    write_vals['is_doctor_1'] = False

                                _logger.info(
                                    f"[referral.signup._signup_with_values] Calling partner.write() with vals: {write_vals}"
                                )
                                partner.write(write_vals)

                                # Re-read partner to verify write succeeded
                                partner.invalidate_recordset()
                                _logger.info(
                                    f"[referral.signup._signup_with_values] AFTER WRITE - Partner {partner.id}: "
                                    f"user_id={partner.user_id.id if partner.user_id else False} (expected {salesperson_id}), "
                                    f"referral_salesperson_id={partner.referral_salesperson_id.id if partner.referral_salesperson_id else False} (expected {salesperson_id}), "
                                    f"referred_by_id={partner.referred_by_id.id if partner.referred_by_id else False}, "
                                    f"referral_level={partner.referral_level}, "
                                    f"is_salesperson_onboarded={partner.is_salesperson_onboarded}, "
                                    f"is_doctor_1={partner.is_doctor_1}"
                                )
                            elif salesperson_id and referring_partner.referral_level == 1:
                                # Referred by Doctor 1 (level 1) - this is Doctor 2/3/4
                                partner.write({
                                    'referred_by_id': referring_partner.id,
                                    'referral_salesperson_id': salesperson_id,
                                    'user_id': salesperson_id,
                                    'is_doctor_referred': True,
                                    'referral_level': 2,  # Doctor 2/3/4
                                })
                                _logger.info(
                                    f"[referral.signup._signup_with_values] Partner {partner.id} set as Doctor 2/3/4 (level 2) "
                                    f"(referred by Doctor 1 {referring_partner.id}), salesperson: {salesperson_id}"
                                )
                            elif referring_partner.referral_level == 2:
                                # Referred by Doctor 2/3/4 (level 1) - assign company property user
                                company_property_user_id = request.env['ir.config_parameter'].sudo().get_param(
                                    'ox_doctor_referral_program.company_property_user_id', False
                                )
                                if company_property_user_id:
                                    try:
                                        company_property_user_id = int(company_property_user_id)
                                        # Verify user exists and is active
                                        company_user = request.env['res.users'].sudo().browse(company_property_user_id)
                                        if company_user.exists() and company_user.active:
                                            partner.write({
                                                'referred_by_id': referring_partner.id,
                                                'referral_type': 'company',
                                                'referral_level': 999,
                                                'referral_salesperson_id': False,
                                                'user_id': company_property_user_id,  # Assign company property user
                                            })
                                            _logger.info(
                                                f"[referral.signup._signup_with_values] Partner {partner.id} set as company referral "
                                                f"(referred by Doctor 2/3/4 {referring_partner.id}), "
                                                f"assigned company property user: {company_property_user_id}"
                                            )
                                        else:
                                            # User not found or inactive
                                            partner.write({
                                                'referred_by_id': referring_partner.id,
                                                'referral_type': 'company',
                                                'referral_level': 999,
                                                'referral_salesperson_id': False,
                                                'user_id': False,
                                            })
                                            _logger.warning(
                                                f"[referral.signup._signup_with_values] Company property user {company_property_user_id} "
                                                f"not found or inactive. Partner {partner.id} set without user assignment."
                                            )
                                    except (ValueError, TypeError):
                                        # Invalid user ID format
                                        partner.write({
                                            'referred_by_id': referring_partner.id,
                                            'referral_type': 'company',
                                            'referral_level': 999,
                                            'referral_salesperson_id': False,
                                            'user_id': False,
                                        })
                                        _logger.warning(
                                            f"[referral.signup._signup_with_values] Invalid company property user ID format. "
                                            f"Partner {partner.id} set without user assignment."
                                        )
                                else:
                                    # No company property user configured
                                    partner.write({
                                        'referred_by_id': referring_partner.id,
                                        'referral_type': 'company',
                                        'referral_level': 999,
                                        'referral_salesperson_id': False,
                                        'user_id': False,
                                    })
                                    _logger.info(
                                        f"[referral.signup._signup_with_values] Partner {partner.id} set as company referral "
                                        f"(referred by Doctor 2/3/4 {referring_partner.id}), no company property user configured"
                                    )
                            else:
                                # Referred by level 2+ referrals - company referral without user
                                partner.write({
                                    'referred_by_id': referring_partner.id,
                                    'referral_type': 'company',
                                    'referral_level': 999,
                                    'referral_salesperson_id': False,
                                    'user_id': False,
                                })
                                _logger.info(
                                    f"[referral.signup._signup_with_values] Partner {partner.id} set as company referral "
                                    f"(referred by {referring_partner.id}, level {referring_partner.referral_level}) - no user"
                                )
                            
                            _logger.info(
                                f"[referral.signup._signup_with_values] Partner {partner.id} registered via referral code {referral_code} "
                                f"from partner {referring_partner.id}. "
                                f"Salesperson: {partner.referral_salesperson_id.id if partner.referral_salesperson_id else 'None'}, "
                                f"Level: {partner.referral_level}"
                            )
                        else:
                            _logger.warning(
                                f"[referral.signup._signup_with_values] Invalid referral code: {referral_code}"
                            )
                    else:
                        _logger.info(
                            f"[referral.signup._signup_with_values] Partner {partner.id} already has referral chain "
                            f"(referred_by_id={partner.referred_by_id.id}), skipping duplicate processing"
                        )
                    
                    # Clear referral code from session after processing
                    if referral_code:
                        request.session.pop('referral_code', None)
                except Exception as e:
                    _logger.error(
                        f"[referral.signup._signup_with_values] Error processing referral code {referral_code}: {str(e)}",
                        exc_info=True
                    )
            else:
                # No referral code - direct signup without referral link
                # Assign company property user if configured
                # Only assign if partner doesn't already have a user_id or referred_by_id
                if not partner.user_id and not partner.referred_by_id:
                    company_property_user_id = request.env['ir.config_parameter'].sudo().get_param(
                        'ox_doctor_referral_program.company_property_user_id', False
                    )
                    if company_property_user_id:
                        try:
                            company_property_user_id = int(company_property_user_id)
                            # Verify user exists and is active
                            company_user = request.env['res.users'].sudo().browse(company_property_user_id)
                            if company_user.exists() and company_user.active:
                                partner.write({
                                    'referral_type': 'company',
                                    'referral_level': 999,
                                    'referral_salesperson_id': False,
                                    'user_id': company_property_user_id,  # Assign company property user
                                })
                                _logger.info(
                                    f"[referral.signup._signup_with_values] Partner {partner.id} signed up directly "
                                    f"without referral link, assigned company property user: {company_property_user_id}"
                                )
                            else:
                                _logger.warning(
                                    f"[referral.signup._signup_with_values] Company property user {company_property_user_id} "
                                    f"not found or inactive."
                                )
                        except (ValueError, TypeError):
                            _logger.warning(
                                f"[referral.signup._signup_with_values] Invalid company property user ID format."
                            )
                    else:
                        _logger.info(
                            f"[referral.signup._signup_with_values] Partner {partner.id} signed up directly "
                            f"without referral link, no company property user configured"
                        )
        
        # Clear referral code from session after processing
        if referral_code:
            request.session.pop('referral_code', None)
        
        # Clear referral code from session after processing
        if referral_code:
            request.session.pop('referral_code', None)
        
        return result

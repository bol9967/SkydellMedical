# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo.http import request
from odoo.exceptions import ValidationError, UserError
from odoo.addons.auth_signup.models.res_users import SignupError
from odoo import _
from markupsafe import Markup
import werkzeug
from werkzeug.urls import url_encode
import logging

_logger = logging.getLogger(__name__)


class AuthSignupHomeNPI(AuthSignupHome):

    def _proceed_with_invitation_flow(self, qcontext, signup_name, npi_number, npi_data):
        """Helper method to proceed with invitation flow (NPI validation → Terms → 2FA)"""
        # Extract gender from NPI data if available
        basic = npi_data.get('basic', {}) if npi_data else {}
        sex = basic.get('sex', '')
        gender_map = {'F': 'female', 'M': 'male'}
        npi_gender = gender_map.get(sex, '') if sex else ''
        
        _logger.info("NPI validation successful, storing signup data in session")
        # Store signup data in session for Terms & Conditions step
        # Odoo automatically saves session when we modify it
        request.session['signup_data'] = {
            'token': qcontext.get('token'),
            'login': qcontext.get('login'),
            'name': signup_name,
            'password': qcontext.get('password'),
            'npi_number': npi_number,
            'npi_data': npi_data,  # Store validated NPI data
            'npi_gender': npi_gender,  # Store gender for later use
        }
        _logger.info("Signup data stored in session for user: %s, Session ID: %s, Gender: %s", 
                   qcontext.get('login'), getattr(request.session, 'sid', 'N/A'), npi_gender)
        
        # For portal/public users, continue with Terms & Conditions and 2FA
        # Check if Terms & Conditions are required
        terms_obj = request.env['terms.conditions'].sudo()
        current_terms = terms_obj.get_current_terms()
        
        if current_terms:
            _logger.info("Terms & Conditions found (ID: %s), redirecting to Terms page", current_terms.id)
            # Redirect to Terms & Conditions page
            # Odoo will automatically save session before redirect
            response = request.redirect('/web/signup/terms')
            _logger.info("Redirecting to Terms page")
            return response
        else:
            _logger.info("No Terms & Conditions configured, redirecting to 2FA")
            # No terms configured, but 2FA is still required
            # Redirect to 2FA page instead of completing signup
            response = request.redirect('/web/signup/2fa')
            _logger.info("Redirecting to 2FA page (no Terms configured)")
            return response

    @http.route('/web/reset_password', type='http', auth='public', website=True, sitemap=False)
    def web_auth_reset_password(self, *args, **kw):
        """Override to handle password reset - skip NPI validation, Terms & Conditions, and 2FA"""
        # Ensure public user context for website access
        try:
            public_user = request.env.ref('base.public_user').sudo()
            if request.env.user.id != public_user.id:
                request.update_env(user=public_user)
        except Exception as e:
            _logger.warning("Error ensuring public user context: %s", str(e))
        
        qcontext = self.get_auth_signup_qcontext()

        if not qcontext.get('token') and not qcontext.get('reset_password_enabled'):
            raise werkzeug.exceptions.NotFound()

        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                if not request.env['ir.http']._verify_request_recaptcha_token('password_reset'):
                    raise UserError(_("Suspicious activity detected by Google reCaptcha."))
                if qcontext.get('token'):
                    # Password reset with token - just set password, skip all validation steps
                    _logger.info("Password reset with token - skipping NPI validation, Terms & Conditions, and 2FA")
                    self.do_signup(qcontext)
                    return self.web_login(*args, **kw)
                else:
                    # Password reset without token - send reset email
                    login = qcontext.get('login')
                    assert login, _("No login provided.")
                    _logger.info(
                        "Password reset attempt for <%s> by user <%s> from %s",
                        login, request.env.user.login, request.httprequest.remote_addr)
                    request.env['res.users'].sudo().reset_password(login)
                    qcontext['message'] = _("Password reset instructions sent to your email")
            except UserError as e:
                qcontext['error'] = e.args[0]
            except SignupError:
                qcontext['error'] = _("Could not reset your password")
                _logger.exception('error when resetting password')
            except Exception as e:
                qcontext['error'] = str(e)

        elif 'signup_email' in qcontext:
            user = request.env['res.users'].sudo().search([('email', '=', qcontext.get('signup_email')), ('state', '!=', 'new')], limit=1)
            if user:
                return request.redirect('/web/login?%s' % url_encode({'login': user.login, 'redirect': '/web'}))

        response = request.render('auth_signup.reset_password', qcontext)
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
        return response

    def get_auth_signup_qcontext(self):
        """Override to include npi_number in qcontext and detect internal user invitations"""
        qcontext = super().get_auth_signup_qcontext()
        # Add npi_number from request params if present
        if 'npi_number' in request.params:
            qcontext['npi_number'] = request.params.get('npi_number')
        # Also add from session if present
        signup_data = request.session.get('signup_data', {})
        if signup_data.get('npi_number'):
            qcontext['npi_number'] = signup_data.get('npi_number')
        
        # Check if this is an internal user invitation (not portal)
        # Internal users have share=False, portal users have share=True
        is_internal_invitation = False
        partner = None
        if qcontext.get('token'):
            try:
                # Get partner from token to check user type and get NPI
                partner = request.env['res.partner'].sudo()._get_partner_from_token(qcontext.get('token'))
                if partner:
                    # Get NPI from partner if it exists (for password set page)
                    if partner.npi_number and not qcontext.get('npi_number'):
                        qcontext['npi_number'] = partner.npi_number
                        _logger.info("Retrieved NPI from partner %s: %s", partner.id, partner.npi_number)
                    
                    if partner.user_ids:
                        # Partner has users - check if any are internal (share=False)
                        # If any user is internal, it's an internal invitation
                        has_internal = any(not user.share for user in partner.user_ids)
                        is_internal_invitation = has_internal
                        _logger.info("Partner %s has %d user(s) - Internal invitation: %s", 
                                   partner.id, len(partner.user_ids), is_internal_invitation)
                    else:
                        # Partner exists but no users yet - this is a new invitation
                        # Check if there's a user being created for this partner (state='new')
                        # In Odoo, when you invite a user, they might be created in 'new' state first
                        new_user = request.env['res.users'].sudo().search([
                            ('partner_id', '=', partner.id),
                            ('state', '=', 'new')
                        ], limit=1)
                        if new_user:
                            # User exists in 'new' state - check if it's internal
                            is_internal_invitation = not new_user.share
                            _logger.info("Found new user for partner %s - Internal invitation: %s (share=%s)", 
                                       partner.id, is_internal_invitation, new_user.share)
                        else:
                            # No users at all - default to portal (safer, shows NPI field)
                            is_internal_invitation = False
                            _logger.info("Partner %s has no users - assuming portal invitation", partner.id)
            except Exception as e:
                _logger.warning("Error checking user type from token: %s", str(e), exc_info=True)
                # Default to portal if we can't determine (safer - shows NPI field)
                is_internal_invitation = False
        
        qcontext['is_internal_invitation'] = is_internal_invitation
        _logger.info("Signup context - Token: %s, Internal invitation: %s, NPI: %s", 
                    bool(qcontext.get('token')), is_internal_invitation, qcontext.get('npi_number'))
        return qcontext

    @http.route('/web/signup/validate_npi', type='json', auth='public', methods=['POST'], csrf=False)
    def validate_npi(self, npi_number=None, signup_name=None, **kw):
        """JSON endpoint to validate NPI number in real-time"""
        # Extract from JSON-RPC params if available
        json_params = {}
        if hasattr(request, 'jsonrequest') and request.jsonrequest:
            json_params = request.jsonrequest.get('params', {})
        
        npi_number = npi_number or json_params.get('npi_number') or kw.get('npi_number')
        signup_name = signup_name or json_params.get('signup_name') or kw.get('signup_name')
        
        _logger.info("NPI validation request received: %s, Name: %s", npi_number, signup_name)
        if not npi_number:
            _logger.warning("NPI validation failed: NPI number is required")
            return {'valid': False, 'message': 'NPI number is required.', 'field': 'npi_number'}
        
        partner_obj = request.env['res.partner'].sudo()
        is_valid, message, data, error_field = partner_obj.validate_npi(npi_number, signup_name=signup_name)
        
        if is_valid:
            _logger.info("NPI validation successful: %s", npi_number)
        else:
            _logger.warning("NPI validation failed: %s - %s, Error field: %s", npi_number, message, error_field)
        
        return {
            'valid': is_valid,
            'message': message,
            'data': data if is_valid else None,
            'error_field': error_field  # Indicate which field has the error
        }

    @http.route('/web/signup/terms/accept', type='json', auth='public', methods=['POST'], csrf=False)
    def web_signup_terms_accept_json(self, name=None, signature=None, scrolled_to_bottom=None, terms_id=None, **kw):
        """JSON endpoint for OWL signature component - receives JSON-RPC format"""
        try:
            # Odoo automatically extracts params from JSON-RPC and passes them as function parameters
            # But we can also check jsonrequest for additional params
            json_params = {}
            if hasattr(request, 'jsonrequest') and request.jsonrequest:
                json_params = request.jsonrequest.get('params', {})
            
            # Get parameters - Odoo passes them as function params, but also check jsonrequest
            name = name or json_params.get('name') or kw.get('name')
            signature = signature or json_params.get('signature') or kw.get('signature')
            scrolled_to_bottom = scrolled_to_bottom if scrolled_to_bottom is not None else (json_params.get('scrolled_to_bottom') or kw.get('scrolled_to_bottom'))
            terms_id = terms_id or json_params.get('terms_id') or kw.get('terms_id')
            
            _logger.info("Terms acceptance JSON request - Name: %s, Signature: %s, Scrolled: %s, Terms ID: %s", 
                        name, bool(signature), scrolled_to_bottom, terms_id)
            _logger.info("Function params - name: %s, signature: %s, scrolled: %s, terms_id: %s", 
                        name, bool(signature), scrolled_to_bottom, terms_id)
            _logger.info("JSON params: %s, KW: %s", json_params, kw)
            
            signup_data = request.session.get('signup_data', {})
            if not signup_data:
                return {'error': 'Session expired. Please start signup again.'}
            
            # Get terms_id from function param, JSON params, request params, or session (in that order)
            terms_id = terms_id or json_params.get('terms_id') or request.params.get('terms_id') or signup_data.get('terms_id')
            
            # If still no terms_id, get current terms from database
            if not terms_id:
                terms_obj = request.env['terms.conditions'].sudo()
                current_terms = terms_obj.get_current_terms()
                if current_terms:
                    terms_id = current_terms.id
                    _logger.info("Retrieved current terms ID from database: %s", terms_id)
            
            if not terms_id:
                _logger.error("No terms_id found in request, params, session, or database")
                return {'error': 'Terms & Conditions not found. Please refresh and try again.'}
            
            # Get scroll status - default to True if not provided (signature is the final validation)
            scrolled_to_bottom = scrolled_to_bottom if scrolled_to_bottom is not None else True
            
            # Validate signature (this is the primary requirement)
            if not name or len(name.strip()) < 3:
                return {'error': 'Please enter your full name.'}
            
            if not signature:
                return {'error': 'Please provide your signature.'}
            
            # Scroll validation is informational - signature is the final point
            # We'll log if they didn't scroll but won't block them
            if not scrolled_to_bottom:
                _logger.info("User accepted terms with signature but may not have scrolled to bottom")
            
            # Store terms acceptance in signup data
            signature_image = 'data:image/png;base64,' + signature
            signup_data['terms_accepted'] = True
            signup_data['terms_id'] = int(terms_id)
            signup_data['digital_signature'] = signature_image
            signup_data['digital_signature_name'] = name.strip()
            signup_data['ip_address'] = request.httprequest.remote_addr
            signup_data['user_agent'] = request.httprequest.headers.get('User-Agent', '')
            signup_data['scrolled_to_bottom'] = scrolled_to_bottom
            
            # Store in session - ensure it's saved
            # Store in both signup_data and a separate key for redundancy
            request.session['signup_data'] = signup_data
            request.session['terms_accepted_flag'] = True
            request.session['terms_accepted_data'] = {
                'terms_id': int(terms_id),
                'digital_signature': signature_image,
                'digital_signature_name': name.strip(),
                'ip_address': request.httprequest.remote_addr,
                'user_agent': request.httprequest.headers.get('User-Agent', ''),
            }
            # Mark session as modified to ensure it's saved
            request.session.modified = True
            
            # Force session save - Odoo sessions are saved at end of request, but we need to ensure it happens
            # Try to trigger session save by accessing session attributes
            try:
                # Access session ID to ensure session is initialized
                session_id = getattr(request.session, 'sid', None)
                _logger.info("Session ID: %s", session_id)
                
                # Force a session save by committing any pending changes
                request.env.cr.commit()
            except Exception as e:
                _logger.warning("Error during session commit: %s", str(e))
            
            _logger.info("Stored signup data - Terms ID: %s, Name: %s, Signature: %s, IP: %s, Terms Accepted: %s", 
                        signup_data['terms_id'], signup_data['digital_signature_name'], 
                        bool(signup_data['digital_signature']), signup_data['ip_address'],
                        signup_data.get('terms_accepted'))
            
            # Verify session was stored - read it back to confirm
            # Use a fresh read to ensure we're getting the latest data
            stored_data = dict(request.session.get('signup_data', {}))
            stored_flag = request.session.get('terms_accepted_flag', False)
            _logger.info("Session verification - Terms Accepted: %s, Flag: %s, Has signature: %s, Keys: %s", 
                        stored_data.get('terms_accepted'), stored_flag, bool(stored_data.get('digital_signature')),
                        list(stored_data.keys()) if stored_data else [])
            
            # Store T&C acceptance and redirect to 2FA instead of completing signup
            _logger.info("Terms accepted, redirecting to 2FA page")
            return {
                'force_refresh': True,
                'redirect_url': '/web/signup/2fa'
            }
        except Exception as e:
            _logger.error("Error in terms acceptance endpoint: %s", str(e), exc_info=True)
            import traceback
            _logger.error("Full traceback: %s", traceback.format_exc())
            # Always return JSON, even on error
            return {
                'error': f'An error occurred: {str(e)}. Please try again.'
            }

    @http.route('/web/signup/terms', type='http', auth='public', website=True, sitemap=False, methods=['GET', 'POST'])
    def web_signup_terms(self, **kw):
        """Step 2: Terms & Conditions acceptance page"""
        # Ensure public user context for website access
        try:
            public_user = request.env.ref('base.public_user').sudo()
            if request.env.user.id != public_user.id:
                request.update_env(user=public_user)
        except Exception as e:
            _logger.warning("Error ensuring public user context: %s", str(e))
        
        _logger.info("Terms & Conditions page accessed - Method: %s", request.httprequest.method)
        
        # Get signup data from session
        signup_data = request.session.get('signup_data', {})
        _logger.info("Signup data from session: %s", bool(signup_data))
        
        if not signup_data:
            _logger.warning("No signup data in session, redirecting to signup page")
            # Redirect back to signup if no data in session
            return request.redirect('/web/signup')
        
        # Get current terms
        terms_obj = request.env['terms.conditions'].sudo()
        current_terms = terms_obj.get_current_terms()
        _logger.info("Current terms found: %s (ID: %s)", bool(current_terms), current_terms.id if current_terms else None)
        
        if not current_terms:
            _logger.info("No terms configured, skipping Terms page and redirecting to 2FA")
            # No terms configured, skip Terms page but still require 2FA
            # Redirect to 2FA page
            return request.redirect('/web/signup/2fa')
        
        # Store terms_id in session for JSON endpoint
        if current_terms:
            signup_data['terms_id'] = current_terms.id
            request.session['signup_data'] = signup_data
            _logger.info("Stored terms_id in session: %s", current_terms.id)
        
        qcontext = {
            'terms': current_terms,
            'signup_data': signup_data,
        }
        
        if request.httprequest.method == 'POST':
            _logger.info("Processing Terms acceptance POST request")
            # Check if this is a signature submission from OWL component
            if request.params.get('name') and request.params.get('signature'):
                # This is from OWL signature component
                signature_name = request.params.get('name', '').strip()
                signature_image = 'data:image/png;base64,' + request.params.get('signature', '').strip()
                terms_id = request.params.get('terms_id')
                scrolled_to_bottom = request.params.get('scrolled_to_bottom', 'false') == 'true'
                
                _logger.info("Terms acceptance data (OWL) - Signature image: %s, Signature name: %s, Terms ID: %s, Scrolled: %s", 
                            bool(signature_image), signature_name, terms_id, scrolled_to_bottom)
                
                if not scrolled_to_bottom:
                    _logger.warning("Terms acceptance failed: User did not scroll to bottom")
                    qcontext['error'] = 'Please scroll to the bottom of the Terms & Conditions before accepting.'
                    return request.render('ox_partner_npi.signup_terms', qcontext)
                
                if not signature_name or len(signature_name.strip()) < 3:
                    _logger.warning("Terms acceptance failed: Signature name missing or too short")
                    qcontext['error'] = 'Please enter your full name.'
                    return request.render('ox_partner_npi.signup_terms', qcontext)
                
                if not signature_image or len(signature_image) < 50:
                    _logger.warning("Terms acceptance failed: Digital signature image missing")
                    qcontext['error'] = 'Please provide your signature.'
                    return request.render('ox_partner_npi.signup_terms', qcontext)
                
                # Store terms acceptance in signup data
                signup_data['terms_accepted'] = True
                signup_data['terms_id'] = int(terms_id)
                signup_data['digital_signature'] = signature_image
                signup_data['digital_signature_name'] = signature_name
                signup_data['ip_address'] = request.httprequest.remote_addr
                signup_data['user_agent'] = request.httprequest.headers.get('User-Agent', '')
                request.session['signup_data'] = signup_data
                _logger.info("Terms acceptance stored in session, completing signup")
                
                # Redirect to 2FA instead of completing signup
                request.session['signup_data'] = signup_data
                _logger.info("Terms accepted, redirecting to 2FA page")
                return request.redirect('/web/signup/2fa')
            else:
                # Regular form submission (fallback)
                signature_image = request.params.get('digital_signature', '').strip()
                signature_name = request.params.get('signature_name', '').strip()
                terms_id = request.params.get('terms_id')
                scrolled_to_bottom = request.params.get('scrolled_to_bottom', 'false') == 'true'
                
                _logger.info("Terms acceptance data - Signature image: %s, Signature name: %s, Terms ID: %s, Scrolled: %s", 
                            bool(signature_image), signature_name, terms_id, scrolled_to_bottom)
                
                if not scrolled_to_bottom:
                    _logger.warning("Terms acceptance failed: User did not scroll to bottom")
                    qcontext['error'] = 'Please scroll to the bottom of the Terms & Conditions before accepting.'
                    return request.render('ox_partner_npi.signup_terms', qcontext)
                
                if not signature_name or len(signature_name.strip()) < 3:
                    _logger.warning("Terms acceptance failed: Signature name missing or too short")
                    qcontext['error'] = 'Please enter your full name.'
                    return request.render('ox_partner_npi.signup_terms', qcontext)
                
                if not signature_image:
                    _logger.warning("Terms acceptance failed: Digital signature image missing")
                    qcontext['error'] = 'Please draw your signature.'
                    return request.render('ox_partner_npi.signup_terms', qcontext)
                
                # Store terms acceptance in signup data
                signup_data['terms_accepted'] = True
                signup_data['terms_id'] = int(terms_id)
                signup_data['digital_signature'] = signature_image
                signup_data['digital_signature_name'] = signature_name
                signup_data['ip_address'] = request.httprequest.remote_addr
                signup_data['user_agent'] = request.httprequest.headers.get('User-Agent', '')
                request.session['signup_data'] = signup_data
                _logger.info("Terms acceptance stored in session, completing signup")
                
                # Redirect to 2FA instead of completing signup
                request.session['signup_data'] = signup_data
                _logger.info("Terms accepted, redirecting to 2FA page")
                return request.redirect('/web/signup/2fa')
        
        _logger.info("Rendering Terms & Conditions page")
        return request.render('ox_partner_npi.signup_terms', qcontext)

    @http.route('/web/signup/2fa', type='http', auth='public', methods=['GET', 'POST'], website=True, csrf=False)
    def web_signup_2fa(self, **kw):
        """Step 3: Two-Factor Authentication page"""
        # Ensure public user context for website access
        try:
            public_user = request.env.ref('base.public_user').sudo()
            if request.env.user.id != public_user.id:
                request.update_env(user=public_user)
        except Exception as e:
            _logger.warning("Error ensuring public user context: %s", str(e))
        
        _logger.info("2FA page accessed - Method: %s", request.httprequest.method)
        
        # Get signup data from session - make a copy to avoid reference issues
        signup_data = dict(request.session.get('signup_data', {}))
        _logger.info("Signup data from session - Exists: %s, Keys: %s", 
                    bool(signup_data), list(signup_data.keys()) if signup_data else [])
        _logger.info("Terms accepted in session: %s", signup_data.get('terms_accepted') if signup_data else None)
        _logger.info("Session ID: %s", getattr(request.session, 'sid', None))
        
        if not signup_data:
            _logger.warning("No signup data in session, redirecting to signup")
            return request.redirect('/web/signup')
        
        # Check if T&C already accepted - check multiple sources
        # 1. Check terms_accepted flag in signup_data
        terms_accepted = signup_data.get('terms_accepted')
        # 2. Check separate terms_accepted_flag in session
        terms_accepted_flag = request.session.get('terms_accepted_flag', False)
        # 3. Check for terms acceptance data in separate key
        terms_data = request.session.get('terms_accepted_data', {})
        
        # Also check for digital_signature as an alternative indicator
        has_signature = bool(signup_data.get('digital_signature')) or bool(terms_data.get('digital_signature'))
        has_terms_id = bool(signup_data.get('terms_id')) or bool(terms_data.get('terms_id'))
        has_signature_name = bool(signup_data.get('digital_signature_name')) or bool(terms_data.get('digital_signature_name'))
        
        _logger.info("Terms check - signup_data flag: %s, session flag: %s, terms_data: %s", 
                    terms_accepted, terms_accepted_flag, bool(terms_data))
        
        # If terms_accepted is missing but we have the flag or terms_data, restore it
        if not terms_accepted and (terms_accepted_flag or terms_data):
            _logger.warning("terms_accepted missing but flag or data present - restoring from backup")
            # Merge terms_data into signup_data
            if terms_data:
                signup_data['terms_accepted'] = True
                signup_data['terms_id'] = terms_data.get('terms_id') or signup_data.get('terms_id')
                signup_data['digital_signature'] = terms_data.get('digital_signature') or signup_data.get('digital_signature')
                signup_data['digital_signature_name'] = terms_data.get('digital_signature_name') or signup_data.get('digital_signature_name')
                if 'ip_address' not in signup_data:
                    signup_data['ip_address'] = terms_data.get('ip_address')
                if 'user_agent' not in signup_data:
                    signup_data['user_agent'] = terms_data.get('user_agent')
            else:
                signup_data['terms_accepted'] = True
            
            # Save back to session
            request.session['signup_data'] = signup_data
            request.session.modified = True
            terms_accepted = True
            _logger.info("Restored terms_accepted from backup - New keys: %s", list(signup_data.keys()))
        
        if not terms_accepted:
            _logger.warning("Terms not accepted (value: %s, flag: %s, has_signature: %s, has_terms_id: %s, has_signature_name: %s), redirecting to T&C page", 
                          terms_accepted, terms_accepted_flag, has_signature, has_terms_id, has_signature_name)
            _logger.info("Full signup_data: %s", signup_data)
            return request.redirect('/web/signup/terms')
        
        email = signup_data.get('login', '')
        if not email:
            _logger.error("No email in signup data")
            return request.redirect('/web/signup')
        
        qcontext = {
            'email': email,
            'email_masked': self._mask_email(email),
            'error': kw.get('error', ''),
            'message': kw.get('message', ''),
        }
        
        # Handle POST - verify OTP
        if request.httprequest.method == 'POST':
            otp_code = kw.get('otp_code', '').strip()
            action = kw.get('action', '')
            
            if action == 'resend':
                # Resend OTP - check rate limiting and cooldown first
                try:
                    rate_limit_check = self._check_otp_rate_limit(email, request.httprequest.remote_addr, is_resend=True)
                    if not rate_limit_check['allowed']:
                        qcontext['error'] = rate_limit_check['message']
                        cooldown = rate_limit_check.get('cooldown_seconds', 0)
                        _logger.warning("OTP resend rate limit exceeded - Email: %s, IP: %s, Cooldown: %s seconds", 
                                      email, request.httprequest.remote_addr, cooldown)
                    else:
                        # Update last resend timestamp in session
                        last_resend_key = f'otp_last_resend_{email}'
                        request.session[last_resend_key] = fields.Datetime.now().isoformat()
                        request.session.modified = True
                        
                        self._send_otp_email(email, signup_data)
                        qcontext['message'] = 'A new verification code has been sent to your email.'
                        _logger.info("OTP resent to: %s", email)
                except Exception as e:
                    _logger.error("Error resending OTP: %s", str(e), exc_info=True)
                    qcontext['error'] = f'Error sending verification code: {str(e)}'
            elif otp_code:
                # Verify OTP
                try:
                    if self._verify_otp(email, otp_code, signup_data):
                        # OTP verified, complete signup
                        _logger.info("OTP verified successfully, completing signup")
                        try:
                            # Clear OTP from session before completing signup
                            request.session.pop('otp_verified', None)
                            # _complete_signup returns a redirect response - return it directly
                            return self._complete_signup(signup_data)
                        except Exception as e:
                            _logger.error("Error completing signup after 2FA: %s", str(e), exc_info=True)
                            qcontext['error'] = f'Error creating account: {str(e)}'
                    else:
                        qcontext['error'] = 'Invalid verification code. Please try again.'
                except Exception as e:
                    _logger.error("OTP verification error: %s", str(e), exc_info=True)
                    qcontext['error'] = str(e)
            # If POST without otp_code and not resend action, it's a form submission attempt
            # Don't show error for empty OTP on resend - let resend work independently
        
        # GET request - Send OTP on first visit (independent per user/session)
        # Check if there's a valid OTP for this specific email/session combination
        if request.httprequest.method == 'GET':
            try:
                session_id = getattr(request.session, 'sid', None) or signup_data.get('otp_session_id')
                if not session_id:
                    # Generate session ID if not available
                    import hashlib
                    import time
                    unique_str = f"{email}_{time.time()}_{request.httprequest.remote_addr}"
                    session_id = hashlib.md5(unique_str.encode()).hexdigest()
                    signup_data['otp_session_id'] = session_id
                    request.session['signup_data'] = signup_data
                    request.session.modified = True
                
                # Check for valid OTP for this specific email/session
                otp_obj = request.env['two.factor.auth'].sudo()
                valid_otp = otp_obj.get_valid_otp(email, session_id)
                has_valid_otp = bool(valid_otp)
                
                _logger.info("2FA GET - Email: %s, Session: %s, Has valid OTP: %s", 
                           email, session_id, has_valid_otp)
                
                # Enterprise-level rate limiting check
                rate_limit_check = self._check_otp_rate_limit(email, request.httprequest.remote_addr, is_resend=False)
                if not rate_limit_check['allowed']:
                    qcontext['error'] = rate_limit_check['message']
                    _logger.warning("OTP rate limit exceeded - Email: %s, IP: %s, Cooldown: %s seconds", 
                                  email, request.httprequest.remote_addr, rate_limit_check.get('cooldown_seconds', 0))
                elif not has_valid_otp:
                    # No valid OTP exists, send a new one
                    _logger.info("No valid OTP found, sending new OTP to: %s", email)
                    self._send_otp_email(email, signup_data)
                    qcontext['message'] = 'A verification code has been sent to your email address.'
                else:
                    # Valid OTP exists, inform user
                    _logger.info("Valid OTP already exists for: %s", email)
                    qcontext['message'] = 'A verification code has already been sent to your email address. Please check your inbox or click "Resend Code" if needed.'
                    
            except Exception as e:
                _logger.error("Error in 2FA GET handler: %s", str(e), exc_info=True)
                import traceback
                _logger.error("Full traceback: %s", traceback.format_exc())
                qcontext['error'] = f'Error sending verification code: {str(e)}. Please try clicking "Resend Code".'
        
        return request.render('ox_partner_npi.signup_2fa', qcontext)

    def _mask_email(self, email):
        """Mask email address for display (e.g., j***@example.com)"""
        if not email or '@' not in email:
            return email
        local, domain = email.split('@', 1)
        if len(local) <= 2:
            masked_local = local[0] + '*'
        else:
            masked_local = local[0] + '*' * (len(local) - 2) + local[-1]
        return f'{masked_local}@{domain}'

    def _check_otp_rate_limit(self, email, ip_address, is_resend=False):
        """Enterprise-level rate limiting for OTP requests
        Returns: {'allowed': bool, 'message': str, 'cooldown_seconds': int}
        """
        try:
            otp_obj = request.env['two.factor.auth'].sudo()
            from datetime import datetime, timedelta
            from odoo import fields
            
            # Get rate limit settings from ir.config_parameter (database settings)
            get_param = request.env['ir.config_parameter'].sudo().get_param
            resend_cooldown = int(get_param('ox_partner_npi.otp_resend_cooldown_seconds', 60))
            max_per_email_hour = int(get_param('ox_partner_npi.otp_max_per_email_per_hour', 5))
            max_per_ip_hour = int(get_param('ox_partner_npi.otp_max_per_ip_per_hour', 10))
            max_per_email_10min = int(get_param('ox_partner_npi.otp_max_per_email_per_10min', 3))
            
            # Resend cooldown: Configurable seconds between resend requests
            if is_resend:
                last_resend_key = f'otp_last_resend_{email}'
                last_resend_time = request.session.get(last_resend_key)
                if last_resend_time:
                    try:
                        from datetime import datetime
                        last_resend = datetime.fromisoformat(last_resend_time) if isinstance(last_resend_time, str) else last_resend_time
                        time_since_last = (fields.Datetime.now() - last_resend).total_seconds()
                        remaining_cooldown = int(resend_cooldown - time_since_last)
                        
                        if time_since_last < resend_cooldown:
                            return {
                                'allowed': False,
                                'message': f'Please wait {remaining_cooldown} seconds before requesting another verification code.',
                                'cooldown_seconds': remaining_cooldown
                            }
                    except Exception as e:
                        _logger.warning("Error parsing last resend time: %s", str(e))
            
            # Rate limit: Max OTPs per email per hour (check all records including expired ones)
            one_hour_ago = fields.Datetime.now() - timedelta(hours=1)
            # Count all OTPs created in the last hour for this email (including verified/expired ones)
            # This includes records that were marked as expired
            email_otp_count = otp_obj.search_count([
                ('email', '=', email),
                ('create_date', '>=', one_hour_ago)
            ])
            
            _logger.info("Rate limit check - Email: %s, OTPs in last hour: %s (limit: %s)", 
                        email, email_otp_count, max_per_email_hour)
            
            if email_otp_count >= max_per_email_hour:
                return {
                    'allowed': False,
                    'message': 'Too many verification code requests. Please wait 1 hour before requesting again.',
                    'cooldown_seconds': 3600
                }
            
            # Rate limit: Max OTPs per IP per hour
            ip_otp_count = otp_obj.search_count([
                ('ip_address', '=', ip_address),
                ('create_date', '>=', one_hour_ago)
            ])
            
            _logger.info("Rate limit check - IP: %s, OTPs in last hour: %s (limit: %s)", 
                        ip_address, ip_otp_count, max_per_ip_hour)
            
            if ip_otp_count >= max_per_ip_hour:
                return {
                    'allowed': False,
                    'message': 'Too many verification code requests from this location. Please try again later.',
                    'cooldown_seconds': 3600
                }
            
            # Rate limit: Max OTPs per email per 10 minutes
            ten_minutes_ago = fields.Datetime.now() - timedelta(minutes=10)
            recent_email_count = otp_obj.search_count([
                ('email', '=', email),
                ('create_date', '>=', ten_minutes_ago)
            ])
            
            _logger.info("Rate limit check - Email: %s, OTPs in last 10 minutes: %s (limit: %s)", 
                        email, recent_email_count, max_per_email_10min)
            
            if recent_email_count >= max_per_email_10min:
                remaining_minutes = int((600 - (fields.Datetime.now() - ten_minutes_ago).total_seconds()) / 60) + 1
                return {
                    'allowed': False,
                    'message': f'Please wait {remaining_minutes} minutes before requesting another verification code.',
                    'cooldown_seconds': remaining_minutes * 60
                }
            
            return {'allowed': True, 'message': '', 'cooldown_seconds': 0}
            
        except Exception as e:
            _logger.error("Error checking OTP rate limit: %s", str(e))
            # Allow on error to not block legitimate users
            return {'allowed': True, 'message': '', 'cooldown_seconds': 0}

    def _send_otp_email(self, email, signup_data):
        """Send OTP code via email"""
        # Get session ID - Odoo uses 'sid' attribute
        session_id = getattr(request.session, 'sid', None) or signup_data.get('otp_session_id')
        
        # Fallback: use a combination of email and timestamp as unique identifier
        if not session_id:
            import hashlib
            import time
            # Create a unique session identifier from email and timestamp
            unique_str = f"{email}_{time.time()}_{request.httprequest.remote_addr}"
            session_id = hashlib.md5(unique_str.encode()).hexdigest()
            _logger.warning("Session ID (sid) not available, using generated ID: %s", session_id)
        
        ip_address = request.httprequest.remote_addr
        user_agent = request.httprequest.headers.get('User-Agent', '')
        
        _logger.info("Creating OTP - Email: %s, Session ID: %s", email, session_id)
        
        # Store session_id in signup_data for later verification
        signup_data['otp_session_id'] = session_id
        request.session['signup_data'] = signup_data
        request.session.modified = True
        
        # Create OTP record
        otp_obj = request.env['two.factor.auth'].sudo()
        otp_record, otp_code = otp_obj.create_otp(
            email=email,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
            expiry_minutes=10
        )
        
        # Send email using Odoo 18 native method
        # Use mail.mail model directly (Odoo 18 standard approach)
        try:
            mail_obj = request.env['mail.mail'].sudo()
            body_html = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #333;">Email Verification Code</h2>
                <p>Hello,</p>
                <p>Your verification code for account creation is:</p>
                <div style="background-color: #f4f4f4; padding: 20px; text-align: center; font-size: 32px; font-weight: bold; letter-spacing: 5px; margin: 20px 0;">
                    {otp_code}
                </div>
                <p>This code will expire in 10 minutes.</p>
                <p>If you did not request this code, please ignore this email.</p>
                <p>Best regards,<br/>Odoo Team</p>
            </div>
            """
            # Create mail.mail record (Odoo 18 native method)
            # This is the standard way Odoo 18 sends emails
            mail = mail_obj.create({
                'subject': 'Email Verification Code',
                'email_to': email,
                'body_html': body_html,
                'auto_delete': True,
            })
            _logger.info("Created mail.mail record: %s for email: %s", mail.id, email)
            
            # Send email immediately using Odoo's native method
            # In Odoo 18, calling send() on mail.mail processes the email
            mail.send()
            _logger.info("OTP email sent successfully to: %s (mail.mail ID: %s)", email, mail.id)
            
        except Exception as e:
            _logger.error("Error sending OTP email: %s", str(e), exc_info=True)
            # Log more details about the error
            import traceback
            _logger.error("Full traceback: %s", traceback.format_exc())
            raise

    def _verify_otp(self, email, otp_code, signup_data):
        """Verify OTP code"""
        # Get session ID - Odoo uses 'sid' attribute, fallback to stored value
        session_id = getattr(request.session, 'sid', None)
        
        # If no session_id from session, try to get from signup_data (stored during OTP creation)
        if not session_id:
            session_id = signup_data.get('otp_session_id')
            _logger.info("Using session ID from signup_data: %s", session_id)
        
        if not session_id:
            _logger.error("No session ID available for OTP verification")
            raise ValidationError("Session expired. Please request a new verification code.")
        
        _logger.info("Verifying OTP - Email: %s, Session ID: %s", email, session_id)
        
        otp_obj = request.env['two.factor.auth'].sudo()
        
        # Get valid OTP
        otp_record = otp_obj.get_valid_otp(email, session_id)
        if not otp_record:
            raise ValidationError("No valid verification code found. Please request a new one.")
        
        # Verify
        if otp_record.verify_otp(otp_code):
            request.session['otp_verified'] = True
            signup_data['2fa_verified'] = True
            # Convert datetime to string for JSON serialization
            signup_data['2fa_verified_at'] = fields.Datetime.now().isoformat()
            request.session['signup_data'] = signup_data
            request.session.modified = True
            _logger.info("2FA verified and stored in session")
            return True
        else:
            raise ValidationError(f"Invalid verification code. {otp_record.max_attempts - otp_record.attempts} attempts remaining.")

    def _complete_signup(self, signup_data):
        """Complete the signup process with NPI, Terms acceptance, and 2FA verification"""
        _logger.info("Completing signup process")
        _logger.info("Signup data keys: %s", list(signup_data.keys()))
        _logger.info("Signup data - terms_accepted: %s, 2fa_verified: %s, terms_id: %s, digital_signature: %s", 
                    signup_data.get('terms_accepted'), signup_data.get('2fa_verified'),
                    signup_data.get('terms_id'), bool(signup_data.get('digital_signature')))
        
        # Check if 2FA is verified (required)
        if not signup_data.get('2fa_verified'):
            _logger.error("2FA not verified, cannot complete signup")
            raise ValidationError("Two-factor authentication is required. Please verify your email address.")
        
        # Refresh signup_data from session to ensure we have latest data
        session_signup_data = request.session.get('signup_data', {})
        if session_signup_data:
            signup_data.update(session_signup_data)
            _logger.info("Updated signup_data from session - terms_id: %s, 2fa_verified: %s", 
                        signup_data.get('terms_id'), signup_data.get('2fa_verified'))
        
        token = signup_data.get('token')
        values = {
            'login': signup_data.get('login'),
            'name': signup_data.get('name'),
            'password': signup_data.get('password'),
        }
        npi_number = signup_data.get('npi_number', '').strip()
        
        _logger.info("Signup values - Login: %s, Name: %s, NPI: %s", 
                    values.get('login'), values.get('name'), npi_number)
        
        # Check if this is an internal user signup (skip NPI validation)
        # Note: For invitations, we should check is_internal_invitation flag, not just token existence
        # Token can exist for both internal and portal invitations
        is_internal_user = signup_data.get('is_internal_user', False)
        
        # Validate NPI if provided and not internal user
        # For invitations with token, get partner_id to exclude from uniqueness check
        partner_id = None
        if npi_number and not is_internal_user:
            partner_obj = request.env['res.partner'].sudo()
            # Get partner_id from token if available (for invitations)
            if token:
                try:
                    partner = partner_obj._get_partner_from_token(token)
                    if partner:
                        partner_id = partner.id
                except Exception as e:
                    _logger.warning("Error getting partner from token for NPI validation: %s", str(e))
            
            # Re-validate with name to ensure consistency
            signup_name = signup_data.get('name', '')
            is_valid, message, npi_data, error_field = partner_obj.validate_npi(npi_number, signup_name=signup_name, partner_id=partner_id)
            if not is_valid:
                _logger.error("NPI validation failed during signup completion: %s - %s", npi_number, message)
                qcontext = self.get_auth_signup_qcontext()
                qcontext['error'] = f"❌ NPI Validation Failed: {message}"
                qcontext.update({
                    'name': signup_data.get('name'),
                    'login': signup_data.get('login'),
                    'npi_number': npi_number,
                })
                request.session.pop('signup_data', None)
                return request.render('auth_signup.signup', qcontext)
        
        # Check if user already exists (for public signup without token)
        if not token:
            existing_user = request.env['res.users'].sudo().search([
                ('login', '=', values.get('login'))
            ], limit=1)
            if existing_user:
                _logger.warning("User already exists for public signup: %s", values.get('login'))
                qcontext = self.get_auth_signup_qcontext()
                qcontext['error'] = f'An account with the email address "{values.get("login")}" already exists. Please use a different email or try logging in instead.'
                qcontext.update({
                    'name': signup_data.get('name'),
                    'login': signup_data.get('login'),
                    'npi_number': npi_number,
                })
                request.session.pop('signup_data', None)
                return request.render('auth_signup.signup', qcontext)
        
        try:
            # Call signup to create user or update existing user (if token provided)
            _logger.info("Creating/updating user account for: %s (token: %s)", values.get('login'), bool(token))
            login, password = request.env['res.users'].sudo().signup(values, token)
            _logger.info("User account created/updated successfully: %s", login)
        except Exception as e:
            error_msg = str(e)
            _logger.error("Error creating/updating user account: %s", error_msg, exc_info=True)
            
            # Check if error is due to existing user
            if 'same login' in error_msg.lower() or 'already registered' in error_msg.lower():
                # For invitations with token, if user exists, try to update password directly
                if token:
                    try:
                        partner = request.env['res.partner'].sudo()._get_partner_from_token(token)
                        if partner and partner.user_ids:
                            existing_user = partner.user_ids[0]
                            _logger.info("User exists for invitation, updating password directly: %s", existing_user.login)
                            existing_user.sudo().write({'password': values.get('password')})
                            login = existing_user.login
                            password = values.get('password')
                            _logger.info("Password updated successfully for existing user: %s", login)
                        else:
                            raise
                    except Exception as e2:
                        _logger.error("Error updating password for existing user: %s", str(e2))
                        qcontext = self.get_auth_signup_qcontext()
                        qcontext['error'] = f"Error: {error_msg}. Please contact support."
                        qcontext.update({
                            'name': signup_data.get('name'),
                            'login': signup_data.get('login'),
                            'npi_number': npi_number,
                        })
                        request.session.pop('signup_data', None)
                        return request.render('auth_signup.signup', qcontext)
                else:
                    # Public signup - user already exists
                    qcontext = self.get_auth_signup_qcontext()
                    qcontext['error'] = f'An account with the email address "{values.get("login")}" already exists. Please use a different email or try logging in instead.'
                    qcontext.update({
                        'name': signup_data.get('name'),
                        'login': signup_data.get('login'),
                        'npi_number': npi_number,
                    })
                    request.session.pop('signup_data', None)
                    return request.render('auth_signup.signup', qcontext)
            else:
                # Other error
                qcontext = self.get_auth_signup_qcontext()
                qcontext['error'] = f"Error creating account: {error_msg}"
                qcontext.update({
                    'name': signup_data.get('name'),
                    'login': signup_data.get('login'),
                    'npi_number': npi_number,
                })
                request.session.pop('signup_data', None)
                return request.render('auth_signup.signup', qcontext)
        
        # Find the created user
        user = request.env['res.users'].sudo().search([
            ('login', '=', login)
        ], limit=1)
        
        if user and user.partner_id:
            partner_vals = {}
            
            # Save NPI data (use stored npi_data if available, otherwise re-validate)
            if npi_number:
                partner_obj = request.env['res.partner'].sudo()  # Define partner_obj before using it
                npi_data = signup_data.get('npi_data')
                if not npi_data:
                    signup_name = signup_data.get('name', '')
                    is_valid, message, npi_data, error_field = partner_obj.validate_npi(npi_number, signup_name=signup_name)
                
                if npi_data:
                    partner_vals['npi_number'] = npi_number
                    partner_vals.update(partner_obj._extract_npi_data(npi_data))
                    
                    # Note: Gender from NPI is stored in npi_gender field (not in gender field as res.partner doesn't have gender field in Odoo 18)
                    # The npi_gender field is already included in _extract_npi_data() result
                    _logger.info("NPI data saved to partner: %s (including npi_gender)", user.partner_id.id)
            
            # Save Terms acceptance
            if signup_data.get('terms_accepted'):
                try:
                    terms_id = signup_data.get('terms_id')
                    if not terms_id:
                        # Try to get current terms if not in signup_data
                        terms_obj = request.env['terms.conditions'].sudo()
                        current_terms = terms_obj.get_current_terms()
                        if current_terms:
                            terms_id = current_terms.id
                            _logger.info("Retrieved current terms ID for acceptance: %s", terms_id)
                    
                    if terms_id:
                        acceptance_obj = request.env['terms.acceptance'].sudo()
                        acceptance_obj.create_acceptance(
                            terms_id=terms_id,
                            partner_id=user.partner_id.id,
                            signature_image=signup_data.get('digital_signature'),
                            signature_name=signup_data.get('digital_signature_name', ''),
                            ip_address=signup_data.get('ip_address'),
                            user_agent=signup_data.get('user_agent'),
                            method='signup'
                        )
                        _logger.info("Terms acceptance recorded for partner: %s, Terms ID: %s", 
                                   user.partner_id.id, terms_id)
                    else:
                        _logger.warning("No terms_id available to create acceptance record for partner: %s", user.partner_id.id)
                except Exception as e:
                    _logger.error("Error creating terms acceptance: %s", str(e), exc_info=True)
            
            if partner_vals:
                user.partner_id.sudo().write(partner_vals)
        
        # Commit transaction
        request.env.cr.commit()
        _logger.info("Transaction committed")
        
        # Clear signup data from session
        request.session.pop('signup_data', None)
        
        # Authenticate user (following Odoo 18 native flow)
        try:
            credential = {'login': login, 'password': password, 'type': 'password'}
            auth_info = request.session.authenticate(request.db, credential)
            _logger.info("User authenticated successfully: %s", login)
            
            # Check if user is internal or portal/public for redirect
            from odoo.addons.web.controllers.utils import is_user_internal
            if request.session.uid:
                # Fully logged in - check user type
                if is_user_internal(request.session.uid):
                    # Internal user - redirect to backend
                    redirect_url = '/odoo'
                else:
                    # Portal/Public user - redirect to portal home
                    redirect_url = '/my/home'
                _logger.info("Redirecting to: %s (user type: %s)", redirect_url, 'internal' if is_user_internal(request.session.uid) else 'portal')
                return request.redirect(redirect_url)
            else:
                # Partial session (Odoo native MFA required) - use native redirect logic
                from odoo.addons.web.controllers.utils import _get_login_redirect_url
                redirect_url = _get_login_redirect_url(auth_info['uid'], redirect=None)
                _logger.info("Redirecting to MFA page: %s", redirect_url)
                return request.redirect(redirect_url)
        except Exception as e:
            _logger.error("Error authenticating user: %s", str(e), exc_info=True)
            # Redirect to login page with error
            return request.redirect('/web/login?error=Authentication failed. Please try logging in.')

    @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False)
    def web_auth_signup(self, *args, **kw):
        """Override to add NPI validation and Terms & Conditions step"""
        # Ensure we're using public user context for website access
        # The website module may try to access website records, so ensure proper context
        try:
            # Ensure public user context for website access
            public_user = request.env.ref('base.public_user').sudo()
            if request.env.user.id != public_user.id:
                request.update_env(user=public_user)
            qcontext = self.get_auth_signup_qcontext()
        except Exception as e:
            # If there's an access error, ensure we're using public user
            if 'website' in str(e).lower() or 'Access Denied' in str(e):
                _logger.warning("Website access error, ensuring public user context: %s", str(e))
                try:
                    public_user = request.env.ref('base.public_user').sudo()
                    request.update_env(user=public_user)
                    qcontext = self.get_auth_signup_qcontext()
                except Exception as e2:
                    _logger.error("Error setting public user context: %s", str(e2), exc_info=True)
                    # Fallback: create minimal qcontext without website access
                    qcontext = {
                        'signup_enabled': request.env['res.users'].sudo()._get_signup_invitation_scope() == 'b2c',
                        'token': request.params.get('token') or request.session.get('auth_signup_token'),
                    }
                    if qcontext.get('token'):
                        try:
                            token_infos = request.env['res.partner'].sudo()._signup_retrieve_info(qcontext.get('token'))
                            qcontext.update(token_infos)
                        except:
                            qcontext['error'] = _("Invalid signup token")
                            qcontext['invalid_token'] = True
            else:
                raise

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            raise werkzeug.exceptions.NotFound()

        if 'error' not in qcontext and request.httprequest.method == 'POST':
            try:
                if not request.env['ir.http']._verify_request_recaptcha_token('signup'):
                    raise UserError(_("Suspicious activity detected by Google reCaptcha."))

                # Get NPI and name from request params
                npi_number = request.params.get('npi_number', '').strip()
                signup_name = request.params.get('name', '').strip()
                is_internal_user = qcontext.get('is_internal_invitation', False)  # Check if it's an internal user invitation
                
                # Check if this is a password reset vs invitation using Odoo 18 native signup_type
                # Password reset: signup_type == "reset" → skip all steps, just set password
                # Invitation: signup_type == "signup" or empty → follow all steps for portal users
                # Public signup: no token → follow all steps for portal users
                is_password_reset = False
                signup_type = None
                if qcontext.get('token'):
                    try:
                        partner = request.env['res.partner'].sudo()._get_partner_from_token(qcontext.get('token'))
                        if partner:
                            # Check signup_type from partner (Odoo 18 native way to distinguish)
                            signup_type = partner.signup_type or ''
                            if signup_type == 'reset':
                                # This is a password reset - redirect to reset_password route
                                is_password_reset = True
                                _logger.info("Password reset detected (signup_type='reset') - redirecting to reset_password route")
                                return request.redirect(f'/web/reset_password?token={qcontext.get("token")}')
                            else:
                                # This is an invitation (signup_type='signup' or empty)
                                _logger.info("Invitation detected (signup_type='%s') - following invitation flow", signup_type)
                    except Exception as e:
                        _logger.warning("Error checking signup_type: %s", str(e))
                
                # Determine flow type for logging
                if is_password_reset:
                    flow_type = "Password Reset"
                elif qcontext.get('token'):
                    flow_type = f"Invitation (signup_type='{signup_type}')"
                else:
                    flow_type = "Public Signup"
                
                _logger.info("Signup POST request - Login: %s, Name: %s, NPI: %s, Internal User: %s, Flow Type: %s", 
                           qcontext.get('login'), signup_name, npi_number, is_internal_user, flow_type)
                
                # For internal users, skip NPI validation and Terms/2FA, complete signup directly
                if is_internal_user:
                    _logger.info("Internal user signup - skipping NPI validation, Terms & Conditions, and 2FA")
                    try:
                        # Use native Odoo signup flow for internal users
                        self.do_signup(qcontext)
                        
                        # Set user to public if they were not signed in by do_signup (mfa enabled)
                        if request.session.uid is None:
                            public_user = request.env.ref('base.public_user')
                            request.update_env(user=public_user)
                        
                        # Save NPI data if provided (optional for internal users)
                        if npi_number:
                            User = request.env['res.users']
                            user_sudo = User.sudo().search(
                                User._get_login_domain(qcontext.get('login')), order=User._get_login_order(), limit=1
                            )
                            if user_sudo and user_sudo.partner_id:
                                # Validate and save NPI data
                                partner_obj = request.env['res.partner'].sudo()
                                is_valid, message, npi_data, error_field = partner_obj.validate_npi(npi_number, signup_name=signup_name)
                                if is_valid and npi_data:
                                    partner_vals = {'npi_number': npi_number}
                                    partner_vals.update(partner_obj._extract_npi_data(npi_data))
                                    user_sudo.partner_id.sudo().write(partner_vals)
                                    _logger.info("NPI data saved to internal user partner: %s", user_sudo.partner_id.id)
                        
                        # Send an account creation confirmation email
                        User = request.env['res.users']
                        user_sudo = User.sudo().search(
                            User._get_login_domain(qcontext.get('login')), order=User._get_login_order(), limit=1
                        )
                        template = request.env.ref('auth_signup.mail_template_user_signup_account_created', raise_if_not_found=False)
                        if user_sudo and template:
                            template.sudo().send_mail(user_sudo.id, force_send=True)
                        
                        return self.web_login(*args, **kw)
                    except UserError as e:
                        qcontext['error'] = e.args[0]
                    except (SignupError, AssertionError) as e:
                        if request.env["res.users"].sudo().search_count([("login", "=", qcontext.get("login"))], limit=1):
                            qcontext["error"] = _("Another user is already registered using this email address.")
                        else:
                            _logger.warning("%s", e)
                            qcontext['error'] = _("Could not create a new account.") + Markup('<br/>') + str(e)
                    except werkzeug.exceptions.HTTPException:
                        raise
                    except Exception as e:
                        _logger.error("Unexpected error during internal user signup: %s", str(e), exc_info=True)
                        qcontext['error'] = f"An error occurred during signup: {str(e)}"
                
                # For portal/public users (invitation), NPI is required and follow all steps
                if not npi_number:
                    _logger.warning("Signup failed: NPI number is required for portal signup")
                    qcontext['error'] = '❌ NPI Validation Failed: NPI number is required to complete signup. Please provide a valid NPI number.'
                    # Preserve other form values
                    if 'name' in request.params:
                        qcontext['name'] = request.params.get('name')
                    if 'login' in request.params:
                        qcontext['login'] = request.params.get('login')
                    # Don't proceed with signup, show error
                else:
                    # Validate NPI via API with name validation
                    # Get partner from token if available (for invitations where partner already has NPI)
                    partner_id = None
                    if qcontext.get('token'):
                        try:
                            partner = request.env['res.partner'].sudo()._get_partner_from_token(qcontext.get('token'))
                            if partner:
                                partner_id = partner.id
                                _logger.info("Invitation signup - Partner ID: %s, NPI: %s", partner_id, partner.npi_number)
                        except Exception as e:
                            _logger.warning("Error getting partner from token: %s", str(e))
                    
                    partner_obj = request.env['res.partner'].sudo()
                    is_valid, message, npi_data, error_field = partner_obj.validate_npi(npi_number, signup_name=signup_name, partner_id=partner_id)
                    
                    if not is_valid:
                        _logger.warning("Signup failed: NPI validation failed - %s", message)
                        qcontext['error'] = f"❌ NPI Validation Failed: {message}"
                        qcontext['npi_number'] = npi_number
                        # Also preserve other form values
                        if 'name' in request.params:
                            qcontext['name'] = request.params.get('name')
                        if 'login' in request.params:
                            qcontext['login'] = request.params.get('login')
                        # Don't proceed with signup, show error
                    else:
                        # Check if user with this email already exists (only for public signup, not invitations)
                        login_email = qcontext.get('login', '').strip()
                        if login_email and not qcontext.get('token'):
                            # Only check for existing users in public signup (no token)
                            # For invitations (with token), allow proceeding even if user exists
                            existing_user = request.env['res.users'].sudo().search([
                                ('login', '=', login_email)
                            ], limit=1)
                            if existing_user:
                                # Public signup - user already exists, show error
                                _logger.warning("Public signup failed: User with email %s already exists", login_email)
                                qcontext['error'] = f'An account with the email address "{login_email}" already exists. Please use a different email or try logging in instead.'
                                qcontext['npi_number'] = npi_number
                                # Preserve other form values
                                if 'name' in request.params:
                                    qcontext['name'] = request.params.get('name')
                                # Don't proceed with signup, show error
                            else:
                                # New user signup - proceed with flow
                                return self._proceed_with_invitation_flow(qcontext, signup_name, npi_number, npi_data)
                        else:
                            # Invitation (has token) - proceed with flow even if user exists
                            return self._proceed_with_invitation_flow(qcontext, signup_name, npi_number, npi_data)
                            
            except UserError as e:
                _logger.error("UserError during signup: %s", str(e))
                qcontext['error'] = e.args[0]
            except (SignupError, AssertionError) as e:
                _logger.error("SignupError during signup: %s", str(e), exc_info=True)
                if request.env["res.users"].sudo().search_count([("login", "=", qcontext.get("login"))], limit=1):
                    qcontext["error"] = _("Another user is already registered using this email address.")
                else:
                    _logger.warning("%s", e)
                    qcontext['error'] = _("Could not create a new account.") + Markup('<br/>') + str(e)
            except werkzeug.exceptions.HTTPException:
                # Re-raise redirect exceptions
                raise
            except Exception as e:
                _logger.error("Unexpected error during signup: %s", str(e), exc_info=True)
                qcontext['error'] = f"An error occurred during signup: {str(e)}"

        elif 'signup_email' in qcontext:
            user = request.env['res.users'].sudo().search([('email', '=', qcontext.get('signup_email')), ('state', '!=', 'new')], limit=1)
            if user:
                return request.redirect('/web/login?%s' % url_encode({'login': user.login, 'redirect': '/web'}))

        response = request.render('auth_signup.signup', qcontext)
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
        return response

    def _complete_signup_after_creation(self, signup_data):
        """Complete signup after user is created (for cases without Terms)"""
        _logger.info("Completing signup after user creation")
        npi_number = signup_data.get('npi_number', '').strip()
        
        if npi_number and request.session.uid:
            user = request.env['res.users'].browse(request.session.uid)
            if user and user.partner_id:
                partner_obj = request.env['res.partner'].sudo()
                npi_data = signup_data.get('npi_data')
                if npi_data:
                    partner_vals = {'npi_number': npi_number}
                    partner_vals.update(partner_obj._extract_npi_data(npi_data))
                    user.partner_id.sudo().write(partner_vals)
                    _logger.info("NPI data saved to partner: %s", user.partner_id.id)
        
        request.session.pop('signup_data', None)

    def _format_address(self, addr):
        """Format address dictionary into readable string"""
        parts = []
        if addr.get('address_1'):
            parts.append(addr['address_1'])
        if addr.get('address_2'):
            parts.append(addr['address_2'])
        city = addr.get('city', '')
        state = addr.get('state', '')
        postal = addr.get('postal_code', '')
        if city or state or postal:
            city_state = ', '.join(filter(None, [city, state, postal]))
            parts.append(city_state)
        # API returns 3-character ISO country codes (e.g., 'USA', 'CAN', 'GBR')
        # Only append country if it's not USA
        country_code = addr.get('country_code', '')
        if country_code and country_code not in ('US', 'USA'):
            parts.append(addr.get('country_name', country_code))
        return '\n'.join(parts)


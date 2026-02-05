# -*- coding: utf-8 -*-

import logging
from odoo import http
from odoo.http import request
import base64

_logger = logging.getLogger(__name__)


class ReferralTrackingController(http.Controller):
    """Controller for tracking referral link clicks and shares"""

    @http.route('/ref/click/<string:referral_code>', type='http', auth='public', csrf=False)
    def track_click(self, referral_code, **kwargs):
        """Track a click on a referral link and redirect to signup"""
        try:
            # Get tracking parameters
            utm_source = kwargs.get('utm_source')
            utm_medium = kwargs.get('utm_medium')
            utm_campaign = kwargs.get('utm_campaign')
            utm_content = kwargs.get('utm_content')
            referrer_url = request.httprequest.headers.get('Referer', '')
            
            # Get IP and User Agent
            ip_address = request.httprequest.remote_addr
            user_agent = request.httprequest.headers.get('User-Agent', '')
            
            # Track the click - use sudo() to avoid write_uid issues
            click = request.env['referral.link.click'].sudo().track_click(
                referral_code=referral_code,
                ip_address=ip_address,
                user_agent=user_agent,
                utm_source=utm_source,
                utm_medium=utm_medium,
                utm_campaign=utm_campaign,
                utm_content=utm_content,
                referrer_url=referrer_url
            )
            
            # Run fraud detection checks
            if click:
                fraud_detection = request.env['referral.fraud.detection'].sudo()
                fraud_detection.check_duplicate_ip(referral_code, ip_address)
                fraud_detection.check_duplicate_device(referral_code, click.device_fingerprint)
                fraud_detection.check_velocity(referral_code, ip_address, click.device_fingerprint)
            
            # Redirect to signup with referral code
            signup_url = f"/web/signup?ref={referral_code}"
            
            # Add UTM parameters to signup URL if present
            if utm_source:
                signup_url += f"&utm_source={utm_source}"
            if utm_medium:
                signup_url += f"&utm_medium={utm_medium}"
            if utm_campaign:
                signup_url += f"&utm_campaign={utm_campaign}"
            if utm_content:
                signup_url += f"&utm_content={utm_content}"
            
            return request.redirect(signup_url)
            
        except Exception as e:
            _logger.error(f"Error tracking click: {str(e)}", exc_info=True)
            # Still redirect even if tracking fails
            return request.redirect(f"/web/signup?ref={referral_code}")

    @http.route('/ref/share', type='json', auth='public', methods=['POST'], csrf=False)
    def track_share(self, referral_code, platform, **kwargs):
        """Track a social media share of a referral link"""
        try:
            ip_address = request.httprequest.remote_addr
            user_agent = request.httprequest.headers.get('User-Agent', '')
            
            share = request.env['referral.share'].sudo().track_share(
                referral_code=referral_code,
                platform=platform,
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            return {
                'success': True,
                'share_id': share.id if share else False
            }
        except Exception as e:
            _logger.error(f"Error tracking share: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    @http.route('/ref/qrcode/<string:referral_code>', type='http', auth='public')
    def generate_qrcode(self, referral_code, **kwargs):
        """Generate QR code for referral link"""
        try:
            # Try to import qrcode library
            try:
                import qrcode
                from io import BytesIO
            except ImportError:
                return request.not_found("QR code library not installed. Install with: pip install qrcode[pil]")
            
            # Build referral URL
            base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://localhost:8069')
            referral_url = f"{base_url}/ref/click/{referral_code}"
            
            # Add UTM parameters if provided
            utm_params = []
            if kwargs.get('utm_source'):
                utm_params.append(f"utm_source={kwargs['utm_source']}")
            if kwargs.get('utm_medium'):
                utm_params.append(f"utm_medium={kwargs['utm_medium']}")
            if kwargs.get('utm_campaign'):
                utm_params.append(f"utm_campaign={kwargs['utm_campaign']}")
            
            if utm_params:
                referral_url += "?" + "&".join(utm_params)
            
            # Generate QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(referral_url)
            qr.make(fit=True)
            
            # Create image
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Convert to base64
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            img_str = base64.b64encode(buffer.getvalue()).decode()
            
            # Return as image
            return request.make_response(
                base64.b64decode(img_str),
                headers=[
                    ('Content-Type', 'image/png'),
                    ('Content-Disposition', f'inline; filename="qrcode_{referral_code}.png"')
                ]
            )
            
        except Exception as e:
            _logger.error(f"Error generating QR code: {str(e)}", exc_info=True)
            return request.not_found("Error generating QR code")

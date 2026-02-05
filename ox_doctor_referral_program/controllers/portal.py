# -*- coding: utf-8 -*-

import io
import logging
from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

# Try to import qrcode library
try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False
    _logger.warning("qrcode library not installed. QR code generation will not be available. Install with: pip install qrcode[pil]")


class ReferralPortalController(http.Controller):
    """Controller for referral portal features"""

    @http.route('/referral/qr/<string:code>', type='http', auth='public', website=True)
    def referral_qr_code(self, code, **kwargs):
        """Generate QR code image for referral link

        Args:
            code: The referral code to encode in QR

        Returns:
            PNG image response with QR code
        """
        if not HAS_QRCODE:
            # Return a placeholder or error image if qrcode not installed
            return Response(
                "QR code library not installed",
                status=503,
                content_type='text/plain'
            )

        # Find partner with this referral code
        partner = request.env['res.partner'].sudo().search([
            ('referral_code', '=', code)
        ], limit=1)

        if not partner:
            return Response(
                "Invalid referral code",
                status=404,
                content_type='text/plain'
            )

        # Build the referral URL
        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        referral_url = f"{base_url}/ref/click/{code}"

        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(referral_url)
        qr.make(fit=True)

        # Create image
        img = qr.make_image(fill_color="black", back_color="white")

        # Save to bytes buffer
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        # Return as PNG image
        return Response(
            buffer.getvalue(),
            content_type='image/png',
            headers={
                'Cache-Control': 'public, max-age=86400',  # Cache for 24 hours
            }
        )

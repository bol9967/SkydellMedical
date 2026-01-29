# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    fedex_api_key = fields.Char("FedEx API Key")
    fedex_secret_key = fields.Char("FedEx Secret Key")
    tracking_reminder_min_date = fields.Datetime(
        string="Minimum PO Approval Date for Reminders",
        help="REQUIRED: Only send tracking reminders for POs approved on or after this date. "
             "This excludes all existing/old orders from automatic reminders. "
             "Cron will not run if this date is not configured."
    )
    fedex_tracking_min_date = fields.Datetime(
        string="Minimum Date for FedEx API Tracking",
        help="REQUIRED: Only check FedEx API status for pickings created on or after this date. "
             "This excludes all existing/old pickings from API checks. "
             "Cron will not run if this date is not configured."
    )

    def set_values(self):
        super().set_values()
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('fedex.api_key', self.fedex_api_key or '')
        params.set_param('fedex.secret_key', self.fedex_secret_key or '')
        
        # Handle datetime field - convert to string format for storage
        # REQUIRED: Show error if not set
        if not self.tracking_reminder_min_date:
            raise UserError(_(
                "⚠️ 'Minimum PO Approval Date' is REQUIRED. "
                "Please configure this date to enable tracking reminders. "
                "The cron will not run without this date configured."
            ))
        
        if not self.fedex_tracking_min_date:
            raise UserError(_(
                "⚠️ 'Minimum Date for FedEx API Tracking' is REQUIRED. "
                "Please configure this date to enable FedEx API tracking checks. "
                "The cron will not run without this date configured."
            ))
        
        # Use Odoo's built-in conversion method
        min_date_value = fields.Datetime.to_string(self.tracking_reminder_min_date)
        params.set_param('ox_dropship_tracking_auto.tracking_reminder_min_date', min_date_value)
        
        fedex_min_date_value = fields.Datetime.to_string(self.fedex_tracking_min_date)
        params.set_param('ox_dropship_tracking_auto.fedex_tracking_min_date', fedex_min_date_value)

    @api.model
    def get_values(self):
        res = super().get_values()
        params = self.env['ir.config_parameter'].sudo()
        min_date_str = params.get_param('ox_dropship_tracking_auto.tracking_reminder_min_date', '')
        min_date = False
        if min_date_str:
            try:
                # Use Odoo's built-in conversion method
                min_date = fields.Datetime.from_string(min_date_str)
            except Exception:
                pass
        fedex_min_date_str = params.get_param('ox_dropship_tracking_auto.fedex_tracking_min_date', '')
        fedex_min_date = False
        if fedex_min_date_str:
            try:
                fedex_min_date = fields.Datetime.from_string(fedex_min_date_str)
            except Exception:
                pass
        
        res.update(
            fedex_api_key=params.get_param('fedex.api_key', ''),
            fedex_secret_key=params.get_param('fedex.secret_key', ''),
            tracking_reminder_min_date=min_date,
            fedex_tracking_min_date=fedex_min_date,
        )
        return res


class FedexAPI(models.Model):
    _name = "fedex.api"
    _description = "FedEx API Integration"

    def _get_oauth_token(self):
        """Get OAuth token from FedEx production API."""
        params = self.env['ir.config_parameter'].sudo()
        api_key = params.get_param('fedex.api_key')
        api_secret = params.get_param('fedex.secret_key')

        if not api_key or not api_secret:
            raise ValueError(_("FedEx API key / secret not configured."))

        url = "https://apis.fedex.com/oauth/token"  # ✅ production

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "grant_type": "client_credentials",
            "client_id": api_key,
            "client_secret": api_secret,
        }

        resp = requests.post(url, headers=headers, data=data, timeout=20)
        resp.raise_for_status()
        token = resp.json().get("access_token")
        if not token:
            raise ValueError(_("No access_token returned from FedEx."))
        return token

    def track_shipment(self, tracking_number):
        """Call FedEx production tracking API for a tracking number."""
        token = self._get_oauth_token()

        url = "https://apis.fedex.com/track/v1/trackingnumbers"  # ✅ production

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-locale": "en_US",
        }

        payload = {
            "includeDetailedScans": True,
            "trackingInfo": [{
                "trackingNumberInfo": {
                    "trackingNumber": tracking_number,
                }
            }]
        }

        _logger.info("Calling FedEx track API for %s", tracking_number)
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()

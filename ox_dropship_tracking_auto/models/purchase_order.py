# -*- coding: utf-8 -*-
import re
from datetime import timedelta, datetime
from odoo import api, fields, models, tools, _
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
import logging
import requests

_logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# Regex patterns for typical carrier tracking references
# -------------------------------------------------------------------------
CARRIER_REGEXES = [
    re.compile(r"\b1Z[0-9A-Z]{16}\b", re.I),                              # UPS
    re.compile(r"\b(\d{12,15})\b"),                                       # FedEx (12-15 digits)
    re.compile(r"\b(JJD[0-9]{5,}|JD[0-9]{12,}|[0-9]{10,20})\b", re.I),    # DHL-like
    re.compile(
        r"(?:AWB|Tracking\s*(?:No|#|Number)?\s*[:\-])\s*([A-Z0-9\-]{6,})",
        re.I,
    ),
]


def extract_tracking_numbers(plain_text):
    """Extract probable tracking numbers from supplier email text."""
    text = re.sub(r"[\s\u00A0]+", " ", plain_text or "").strip()
    hits = []
    for rx in CARRIER_REGEXES:
        for m in rx.finditer(text):
            if not m:
                continue
            val = m.group(1) if m.groups() else m.group(0)
            val = (val or "").strip().strip(".,;:")
            if val and val not in hits:
                hits.append(val)

    # Basic sanity filtering
    filtered = [
        h for h in hits if len(h) >= 6 and not h.startswith("+")
    ]
    return filtered


# -------------------------------------------------------------------------
# Purchase Order extension
# -------------------------------------------------------------------------
class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    tracking_last_seen = fields.Char(
        string="Last Tracking Captured", copy=False, readonly=True
    )
    tracking_last_seen_date = fields.Datetime(
        string="Last Tracking Captured On", copy=False, readonly=True
    )
    tracking_reminder_last = fields.Datetime(
        string="Last Tracking Reminder", copy=False, readonly=True
    )
    tracking_reminder_count = fields.Integer(
        string="Tracking Reminders Sent", default=0, copy=False
    )
    tracking_reminder_company_notified = fields.Boolean(
        string="Company Notified (20+ Reminders)", copy=False, readonly=True, default=False
    )
    order_confirmation_sent = fields.Boolean(
        string="Order Confirmation Email Sent", copy=False, readonly=True, default=False
    )

    # ---------------------------------------------------------------
    # Handle incoming supplier emails and auto-capture tracking codes
    # ---------------------------------------------------------------
    def _message_receive_tracking(self, msg_dict):
        """Parse incoming mail body and auto-assign tracking to drop-ship pickings.
        
        Validates tracking number with FedEx API and enforces 24-hour update lock.
        """
        body_html = (msg_dict or {}).get("body") or ""
        plain = tools.html2plaintext(body_html) if body_html else ""
        candidates = extract_tracking_numbers(plain)
        if not candidates:
            return False

        pickings = self._get_related_pickings()
        if not pickings:
            return False

        # Filter out tracking numbers already associated with this PO
        # This prevents false duplicates when email thread contains old tracking numbers
        current_tracking_numbers = set()
        if self.tracking_last_seen:
            current_tracking_numbers.add(self.tracking_last_seen)
        for picking in pickings:
            if picking.carrier_tracking_ref:
                current_tracking_numbers.add(picking.carrier_tracking_ref)
            if picking.fedex_tracking_number:
                current_tracking_numbers.add(picking.fedex_tracking_number)
        
        # Find the first tracking number that's NOT already in this PO
        tracking = None
        for candidate in candidates:
            if candidate not in current_tracking_numbers:
                tracking = candidate
                _logger.info(
                    "Selected new tracking number %s from candidates %s (filtered out existing: %s) for PO %s",
                    tracking, candidates, list(current_tracking_numbers), self.name
                )
                break
        
        # If all candidates are already in this PO, use the first one (might be an update)
        if not tracking:
            tracking = candidates[0]
            _logger.info(
                "All tracking numbers already in PO %s, using first candidate: %s (candidates: %s)",
                self.name, tracking, candidates
            )
        
        # Check 24-hour lock: if tracking was updated more than 24 hours ago, don't allow updates via email
        if self.tracking_last_seen_date:
            hours_since_update = (fields.Datetime.now() - self.tracking_last_seen_date).total_seconds() / 3600
            if hours_since_update >= 24:
                _logger.info(
                    "Tracking update blocked for PO %s: 24-hour lock period expired (%.1f hours since last update)",
                    self.name, hours_since_update
                )
                self.message_post(
                    body=_("Tracking update blocked: More than 24 hours have passed since last tracking update. "
                           "Please contact support to update tracking number manually.")
                )
                return False
        
        # Check for duplicate tracking number in other POs/pickings
        duplicate_info = self._check_duplicate_tracking(tracking)
        if duplicate_info:
            # Send email to supplier about duplicate tracking number
            self._send_duplicate_tracking_email(tracking, duplicate_info)
            self.message_post(
                body=_("❌ Duplicate tracking number rejected: <b>%s</b><br/>"
                       "This tracking number is already associated with %s.<br/>Supplier has been notified.")
                     % (tracking, duplicate_info)
            )
            return False
        
        # Validate tracking number with FedEx API
        is_valid, validation_error = self._validate_tracking_number(tracking)
        if not is_valid:
            # Send email to supplier about invalid tracking number
            self._send_invalid_tracking_email(tracking, validation_error)
            self.message_post(
                body=_("❌ Invalid tracking number received: <b>%s</b><br/>Error: %s<br/>Supplier has been notified.")
                     % (tracking, validation_error or "Tracking number not found in FedEx system")
            )
            return False
        
        # Tracking is valid, proceed with update
        for p in pickings:
            try:
                p.carrier_tracking_ref = tracking
                p.message_post(
                    body=_("✅ Tracking captured from supplier reply: <b>%s</b>") % tracking
                )
                # Send shipped email to customer
                self._send_order_shipped_email(p, tracking)
            except Exception as e:
                _logger.warning("Tracking update failed on picking %s: %s", p.name, e)

        self.tracking_last_seen = tracking
        self.tracking_last_seen_date = fields.Datetime.now()
        self.message_post(
            body=_("Auto-captured tracking from supplier reply: <b>%s</b> (Validated with FedEx)") % tracking
        )
        return True

    # ---------------------------------------------------------------
    # Validate tracking number with FedEx API
    # ---------------------------------------------------------------
    def _validate_tracking_number(self, tracking_number):
        """Validate tracking number with FedEx API.
        
        Returns: (is_valid: bool, error_message: str or None)
        """
        self.ensure_one()
        if not tracking_number:
            return False, "Tracking number is empty"
        
        try:
            FedexAPI = self.env["fedex.api"]
            result = FedexAPI.track_shipment(tracking_number)
            
            # Check if response exists
            if not result:
                return False, "No response from FedEx API"
            
            output = result.get("output", {})
            if not output:
                return False, "No output from FedEx API"
            
            # Check for errors at the output level
            errors = output.get("errors", [])
            if errors:
                error_msg = errors[0].get("message", "Unknown error from FedEx")
                _logger.warning("FedEx API error for tracking %s: %s", tracking_number, error_msg)
                return False, error_msg
            
            # Check for alerts (warnings that might indicate issues)
            alerts = output.get("alerts", [])
            if alerts:
                # Check if any alert indicates the tracking number is invalid
                for alert in alerts:
                    alert_code = alert.get("code", "")
                    alert_message = alert.get("message", "")
                    # Common FedEx error codes for invalid tracking numbers
                    if alert_code in ["TRACKING.NOTFOUND", "TRACKING.INVALID", "TRACKING.NOT.IN.SYSTEM"]:
                        _logger.warning("FedEx API alert for tracking %s: %s - %s", 
                                      tracking_number, alert_code, alert_message)
                        return False, alert_message or "Tracking number not found in FedEx system"
            
            # Check completeTrackResults
            complete_track_results = output.get("completeTrackResults", [])
            if not complete_track_results:
                return False, "Tracking number not found in FedEx system"
            
            # Check each completeTrackResult for errors
            for complete_result in complete_track_results:
                # Check for errors in completeTrackResult
                result_errors = complete_result.get("errors", [])
                if result_errors:
                    error_msg = result_errors[0].get("message", "Unknown error from FedEx")
                    _logger.warning("FedEx completeTrackResult error for tracking %s: %s", 
                                  tracking_number, error_msg)
                    return False, error_msg
                
                # Check trackResults
                track_results = complete_result.get("trackResults", [])
                if not track_results:
                    return False, "Tracking number not found in FedEx system"
                
                # Check each trackResult for errors and valid tracking info
                for track_result in track_results:
                    # Check for errors array in trackResult
                    track_errors = track_result.get("errors", [])
                    if track_errors:
                        error_msg = track_errors[0].get("message", "Unknown error from FedEx")
                        _logger.warning("FedEx trackResult errors array for tracking %s: %s", 
                                      tracking_number, error_msg)
                        return False, error_msg
                    
                    # Check for error object (singular) in trackResult - FedEx uses this format
                    track_error = track_result.get("error", {})
                    if track_error:
                        error_code = track_error.get("code", "")
                        error_msg = track_error.get("message", "Unknown error from FedEx")
                        _logger.warning("FedEx trackResult error object for tracking %s: %s - %s", 
                                      tracking_number, error_code, error_msg)
                        return False, error_msg
                    
                    # Check if tracking number info exists and matches
                    tracking_number_info = track_result.get("trackingNumberInfo", {})
                    if not tracking_number_info:
                        return False, "No tracking information found in FedEx response"
                    
                    # Check if there's actual tracking data (status, events, etc.)
                    latest_status = track_result.get("latestStatusDetail", {})
                    if not latest_status:
                        # If there's no status, it might be invalid
                        return False, "No tracking status found - tracking number may be invalid"
            
            # Tracking number is valid
            _logger.info("Tracking number %s validated successfully for PO %s", tracking_number, self.name)
            return True, None
            
        except requests.exceptions.HTTPError as e:
            # HTTP errors (4xx, 5xx) - likely invalid tracking
            _logger.error("FedEx API HTTP error for tracking %s (PO %s): %s", tracking_number, self.name, e)
            if hasattr(e.response, 'json'):
                try:
                    error_data = e.response.json()
                    error_msg = error_data.get("output", {}).get("errors", [{}])[0].get("message", str(e))
                    return False, error_msg
                except:
                    pass
            return False, "FedEx API error: %s" % str(e)
        except Exception as e:
            _logger.error("FedEx validation error for tracking %s (PO %s): %s", tracking_number, self.name, e)
            # If API call fails unexpectedly, reject the tracking to be safe
            return False, "Unable to validate tracking number: %s" % str(e)
    
    # ---------------------------------------------------------------
    # Send email to supplier about invalid tracking number
    # ---------------------------------------------------------------
    def _send_invalid_tracking_email(self, tracking_number, error_message):
        """Send email to supplier notifying them of invalid tracking number."""
        self.ensure_one()
        
        try:
            error_msg = error_message or "Tracking number not found in FedEx system"
            partner_name = self.partner_id.name or "Supplier"
            if self.partner_id.parent_id:
                partner_name += " (%s)" % self.partner_id.parent_id.name
            
            po_ref = self.name
            if self.partner_ref:
                po_ref += " (%s)" % self.partner_ref
            
            mail_values = {
                "subject": _("%s PO (%s) – Invalid Tracking Number") % (self.company_id.name, self.name),
                "body_html": _(
                    """
                    <div style="margin: 0px; padding: 0px;">
                        <p style="margin: 0px; padding: 0px; font-size: 13px;">
                            Dear %s,
                            <br/><br/>
                            We received a tracking number for Purchase Order
                            <span style="font-weight:bold;">%s</span>.
                            <br/><br/>
                            However, the tracking number <span style="font-weight:bold; color: #d9534f;">%s</span> 
                            could not be validated in the FedEx system.
                            <br/><br/>
                            <strong>Error Details:</strong> %s
                            <br/><br/>
                            Please verify the tracking number and resend the correct tracking information at your earliest convenience.
                            <br/><br/>
                            If you have any questions, please contact us.
                            <br/><br/>
                            Best regards,<br/>
                            %s Purchasing Team
                        </p>
                    </div>
                    """
                ) % (partner_name, po_ref, tracking_number, error_msg, self.company_id.name),
                "email_to": self.partner_id.email,
                "email_from": (
                    self.user_id.email_formatted
                    or self.company_id.email
                    or self.env.user.email_formatted
                ),
            }
            mail = self.env["mail.mail"].sudo().create(mail_values)
            mail.send()
            _logger.info("Invalid tracking notification sent to %s for PO %s, tracking: %s", 
                        self.partner_id.email, self.name, tracking_number)
            
        except Exception as e:
            _logger.error("Failed to send invalid tracking email for PO %s: %s", self.name, e)
    
    # ---------------------------------------------------------------
    # Check for duplicate tracking number
    # ---------------------------------------------------------------
    def _check_duplicate_tracking(self, tracking_number):
        """Check if tracking number already exists in another PO/picking.
        
        Returns: (found_po_name, found_picking_name) or None if no duplicate
        """
        self.ensure_one()
        if not tracking_number:
            return None
        
        # Search for pickings with this tracking number (excluding current PO's pickings)
        current_pickings = self._get_related_pickings()
        current_picking_ids = current_pickings.ids if current_pickings else []
        
        Picking = self.env["stock.picking"]
        duplicate_pickings = Picking.search([
            ("carrier_tracking_ref", "=", tracking_number),
            ("id", "not in", current_picking_ids),
            ("state", "!=", "cancel"),
        ], limit=1)
        
        if duplicate_pickings:
            picking = duplicate_pickings[0]
            # Find the related PO
            po_name = None
            if picking.origin:
                # Try to find PO by origin
                po = self.env["purchase.order"].search([
                    ("name", "=", picking.origin)
                ], limit=1)
                if po:
                    po_name = po.name
                else:
                    po_name = picking.origin
            
            if po_name:
                return "PO %s" % po_name
            else:
                return "Picking %s" % picking.name
        
        # Also check PO tracking_last_seen field
        duplicate_pos = self.env["purchase.order"].search([
            ("tracking_last_seen", "=", tracking_number),
            ("id", "!=", self.id),
            ("state", "in", ["purchase", "done"]),
        ], limit=1)
        
        if duplicate_pos:
            return "PO %s" % duplicate_pos[0].name
        
        return None
    
    # ---------------------------------------------------------------
    # Send duplicate tracking email to supplier
    # ---------------------------------------------------------------
    def _send_duplicate_tracking_email(self, tracking_number, duplicate_info):
        """Send email to supplier notifying them of duplicate tracking number."""
        self.ensure_one()
        
        try:
            partner_name = self.partner_id.name or "Supplier"
            if self.partner_id.parent_id:
                partner_name += " (%s)" % self.partner_id.parent_id.name
            
            po_ref = self.name
            if self.partner_ref:
                po_ref += " (%s)" % self.partner_ref
            
            mail_values = {
                "subject": _("%s PO (%s) – Duplicate Tracking Number") % (self.company_id.name, self.name),
                "body_html": _(
                    """
                    <div style="margin: 0px; padding: 0px;">
                        <p style="margin: 0px; padding: 0px; font-size: 13px;">
                            Dear %s,
                            <br/><br/>
                            We received a tracking number for Purchase Order
                            <span style="font-weight:bold;">%s</span>.
                            <br/><br/>
                            However, the tracking number <span style="font-weight:bold; color: #d9534f;">%s</span> 
                            is already associated with <span style="font-weight:bold;">%s</span> in our system.
                            <br/><br/>
                            <strong>Please verify:</strong>
                            <br/>
                            • Is this tracking number correct for PO %s?
                            <br/>
                            • If yes, please contact us to resolve this issue.
                            <br/>
                            • If no, please provide the correct tracking number for PO %s.
                            <br/><br/>
                            We cannot accept duplicate tracking numbers as they may cause confusion in our order fulfillment process.
                            <br/><br/>
                            If you have any questions, please contact us.
                            <br/><br/>
                            Best regards,<br/>
                            %s Purchasing Team
                        </p>
                    </div>
                    """
                ) % (partner_name, po_ref, tracking_number, duplicate_info, po_ref, po_ref, self.company_id.name),
                "email_to": self.partner_id.email,
                "email_from": (
                    self.user_id.email_formatted
                    or self.company_id.email
                    or self.env.user.email_formatted
                ),
            }
            mail = self.env["mail.mail"].sudo().create(mail_values)
            mail.send()
            _logger.info("Duplicate tracking notification sent to %s for PO %s, tracking: %s (duplicate in %s)", 
                        self.partner_id.email, self.name, tracking_number, duplicate_info)
            
        except Exception as e:
            _logger.error("Failed to send duplicate tracking email for PO %s: %s", self.name, e)
    
    # ---------------------------------------------------------------
    # Send order shipped email to customer
    # ---------------------------------------------------------------
    def _send_order_shipped_email(self, picking, tracking_number):
        """Send order shipped email to customer when tracking is received."""
        self.ensure_one()
        
        try:
            # Get recipient information
            partner = False
            email_to = False
            lang = False
            
            if picking.picking_type_code == "dropship":
                sale = picking.sale_id
                if sale:
                    partner = sale.partner_shipping_id or sale.partner_id or picking.partner_id
                else:
                    partner = picking.partner_id
            else:
                partner = picking.partner_id
            
            if partner:
                email_to = partner.email or False
                lang = partner.lang or self.env.user.lang
            else:
                lang = self.env.user.lang
            
            if not email_to:
                _logger.warning(
                    "Order shipped email skipped for picking %s: no email recipient found (dropship=%s)",
                    picking.name,
                    picking.picking_type_code == "dropship",
                )
                return
            
            # Get email template
            template = self.env.ref(
                "ox_dropship_tracking_auto.email_template_order_shipped",
                raise_if_not_found=False,
            )
            if not template:
                _logger.warning("Email template email_template_order_shipped not found.")
                return
            
            # Send email using template
            # Use only email_to to avoid adding customer as follower to picking
            email_values = {"email_to": email_to}
            
            template.with_context(lang=lang).send_mail(
                picking.id, force_send=True, email_values=email_values
            )
            
            # Post message to picking chatter
            picking.message_post(
                body=_("📦 Order Shipped email sent to customer (%s) with tracking number: <b>%s</b>")
                % (partner.display_name if partner else email_to, tracking_number)
            )
            
            _logger.info(
                "Order shipped email sent to %s for picking %s (type=%s, tracking=%s)",
                email_to,
                picking.name,
                picking.picking_type_code,
                tracking_number,
            )
            
        except Exception as e:
            _logger.error("Failed to send order shipped email for picking %s: %s", picking.name, e)
    
    # ---------------------------------------------------------------
    # Send company notification when 20+ reminders sent
    # ---------------------------------------------------------------
    def _send_max_reminders_company_notification(self):
        """Send email to company when 20 reminders sent but still no tracking."""
        self.ensure_one()
        
        try:
            # Get company email
            company_email = self.company_id.email or False
            if not company_email:
                _logger.warning(
                    "Max reminders notification skipped for PO %s: no company email configured",
                    self.name
                )
                return
            
            # Prepare email content
            partner_name = self.partner_id.name or "Supplier"
            if self.partner_id.parent_id:
                partner_name += " (%s)" % self.partner_id.parent_id.name
            
            po_ref = self.name
            if self.partner_ref:
                po_ref += " (%s)" % self.partner_ref
            
            reminder_count = self.tracking_reminder_count or 0
            last_reminder_date = self.tracking_reminder_last.strftime('%Y-%m-%d %H:%M:%S') if self.tracking_reminder_last else "N/A"
            
            mail_values = {
                "subject": _("⚠️ Alert: %s Reminders Sent for PO %s - No Tracking Received") % (reminder_count, self.name),
                "body_html": _(
                    """
                    <div style="margin: 0px; padding: 0px;">
                        <p style="margin: 0px; padding: 0px; font-size: 13px;">
                            Dear Logistics Team,
                            <br/><br/>
                            <strong style="color: #d9534f;">⚠️ ALERT:</strong> We have sent <strong>%s tracking reminders</strong> 
                            to supplier <strong>%s</strong> for Purchase Order <strong>%s</strong>, 
                            but we have <strong>NOT received a valid tracking number</strong> yet.
                            <br/><br/>
                            <span style="font-weight:bold; text-decoration:underline;">DETAILS:</span><br/>
                            • Purchase Order: <strong>%s</strong><br/>
                            • Supplier: <strong>%s</strong><br/>
                            • Reminders Sent: <strong>%s</strong><br/>
                            • Last Reminder Sent: <strong>%s</strong><br/>
                            • Tracking Number: <strong style="color: #d9534f;">NOT RECEIVED</strong><br/>
                            <br/>
                            <strong>ACTION REQUIRED:</strong><br/>
                            Please follow up with the supplier directly to obtain the tracking information.
                            The system will continue sending reminders until a valid tracking number is received.
                            <br/><br/>
                            Best regards,<br/>
                            Automated Tracking System
                        </p>
                    </div>
                    """
                ) % (reminder_count, partner_name, po_ref, po_ref, partner_name, reminder_count, last_reminder_date),
                "email_to": company_email,
                "email_from": (
                    self.user_id.email_formatted
                    or self.company_id.email
                    or self.env.user.email_formatted
                ),
            }
            mail = self.env["mail.mail"].sudo().create(mail_values)
            mail.send()
            
            self.message_post(
                body=_("📧 Company notification sent: %s reminders sent but no tracking received.") % reminder_count
            )
            
            _logger.info(
                "Max reminders notification sent to %s for PO %s (%s reminders sent)",
                company_email, self.name, reminder_count
            )
            
        except Exception as e:
            _logger.error("Failed to send max reminders notification for PO %s: %s", self.name, e)
    
    # ---------------------------------------------------------------
    # Check for order confirmation keywords
    # ---------------------------------------------------------------
    def _check_order_confirmation(self, msg_dict):
        """Check if vendor email contains 'confirm' or 'confirmed' and send confirmation email to customer."""
        self.ensure_one()
        
        # Skip if already sent
        if self.order_confirmation_sent:
            return False
        
        body_html = (msg_dict or {}).get("body") or ""
        plain = tools.html2plaintext(body_html) if body_html else ""
        subject = (msg_dict or {}).get("subject") or ""
        
        # Check for confirmation keywords (case insensitive)
        confirmation_keywords = ["confirm", "confirmed", "confirmation"]
        text_to_check = (plain + " " + subject).lower()
        
        has_confirmation = any(keyword in text_to_check for keyword in confirmation_keywords)
        
        if not has_confirmation:
            return False
        
        # Find related sale orders (for dropship orders)
        sale_orders = self.env["sale.order"]
        
        # Try to find sale orders through pickings
        pickings = self._get_related_pickings()
        if pickings:
            sale_orders = pickings.mapped("sale_id").filtered(lambda so: so and so.state not in ("cancel", "draft"))
        
        # If no sale orders found through pickings, try to find by origin
        if not sale_orders and self.origin:
            sale_orders = self.env["sale.order"].search([
                ("name", "=", self.origin),
                ("state", "not in", ("cancel", "draft")),
            ])
        
        if not sale_orders:
            _logger.info("No sale orders found for PO %s to send confirmation email", self.name)
            return False
        
        # Send confirmation email to each sale order customer
        for sale_order in sale_orders:
            try:
                self._send_order_confirmation_email(sale_order)
            except Exception as e:
                _logger.error("Failed to send order confirmation email for SO %s (PO %s): %s", 
                            sale_order.name, self.name, e)
        
        # Mark as sent
        self.order_confirmation_sent = True
        self.message_post(
            body=_("📧 Order confirmation email sent to customer(s) based on vendor confirmation.")
        )
        
        return True
    
    # ---------------------------------------------------------------
    # Send order confirmation email to customer
    # ---------------------------------------------------------------
    def _send_order_confirmation_email(self, sale_order):
        """Send order confirmation email to customer."""
        self.ensure_one()
        
        try:
            # Get customer email
            customer_email = sale_order.partner_id.email or False
            if not customer_email:
                _logger.warning(
                    "Order confirmation email skipped for SO %s: no customer email found",
                    sale_order.name
                )
                return
            
            # Get email template
            template = self.env.ref(
                "ox_dropship_tracking_auto.email_template_order_confirmation",
                raise_if_not_found=False,
            )
            if not template:
                _logger.warning("Email template email_template_order_confirmation not found.")
                return
            
            # Send email using template
            # Use only email_to to avoid adding customer as follower to sale order
            email_values = {"email_to": customer_email}
            
            lang = sale_order.partner_id.lang or self.env.user.lang
            template.with_context(lang=lang).send_mail(
                sale_order.id, force_send=True, email_values=email_values
            )
            
            sale_order.message_post(
                body=_("📧 Order confirmation email sent to customer (%s) based on vendor confirmation for PO %s")
                % (sale_order.partner_id.display_name, self.name)
            )
            
            _logger.info(
                "Order confirmation email sent to %s for SO %s (PO %s)",
                customer_email,
                sale_order.name,
                self.name,
            )
            
        except Exception as e:
            _logger.error("Failed to send order confirmation email for SO %s: %s", sale_order.name, e)
    
    # ---------------------------------------------------------------
    # Related pickings (prefer drop-ship type)
    # ---------------------------------------------------------------
    def _get_related_pickings(self):
        self.ensure_one()
        Picking = self.env["stock.picking"]
        picks = Picking.search([("origin", "=", self.name)])
        if not picks:
            picks = Picking.search([("origin", "ilike", self.name)])
        if not picks:
            moves = self.order_line.mapped("move_ids")
            if moves:
                picks = moves.mapped("picking_id")

        if picks:
            drops = picks.filtered(
                lambda p: getattr(p.location_id, "usage", None) == "supplier"
                and getattr(p.location_dest_id, "usage", None) == "customer"
            )
            return drops or picks
        return picks

    def _get_customer_partner_ids(self):
        """
        Get all customer partner IDs linked to this purchase order via sale orders.
        Used to identify customers that must NEVER be followers of purchase orders.
        
        :return: List of customer partner IDs
        """
        self.ensure_one()
        customer_partner_ids = []
        for line in self.order_line:
            if line.sale_line_id and line.sale_line_id.order_id:
                sale_order = line.sale_line_id.order_id
                if sale_order.partner_id:
                    customer_partner_ids.append(sale_order.partner_id.id)
                if sale_order.partner_shipping_id and sale_order.partner_shipping_id.id != sale_order.partner_id.id:
                    customer_partner_ids.append(sale_order.partner_shipping_id.id)
        return list(set(customer_partner_ids))  # Remove duplicates
    
    def message_subscribe(self, partner_ids=None, subtype_ids=None):
        """
        OVERRIDE: PREVENT customers from being subscribed to purchase orders.
        
        This is the PRIMARY prevention mechanism - customers are BLOCKED at the source.
        Aligned with Odoo 18 native message_subscribe signature and behavior.
        """
        # Follow Odoo 18 native pattern: early return if no recordset or no partner_ids
        if not self or not partner_ids:
            return True
        
        # Convert to list (Odoo 18 native pattern)
        partner_ids = partner_ids or []
        
        # Get customer partner IDs that must be excluded
        customer_partner_ids = self._get_customer_partner_ids()
        
        if customer_partner_ids:
            # Filter out any customer partners from the subscription list
            original_count = len(partner_ids)
            partner_ids = [pid for pid in partner_ids if pid not in customer_partner_ids]
            
            if len(partner_ids) < original_count:
                blocked_count = original_count - len(partner_ids)
                _logger.warning(
                    "🔒 PRIVACY PREVENTION: Blocked %d customer partner(s) from being subscribed to PO %s (customer IDs: %s)",
                    blocked_count, self.name, customer_partner_ids
                )
        
        # Only subscribe non-customer partners (call parent if we have valid partners)
        if partner_ids:
            return super().message_subscribe(partner_ids=partner_ids, subtype_ids=subtype_ids)
        # Return True if all partners were filtered out (matches Odoo 18 behavior)
        return True
    
    def _remove_customer_followers(self, customer_partner_ids=None):
        """
        CRITICAL PRIVACY METHOD: Remove any customer partners from purchase order followers.
        
        In dropship business, customers must NEVER be followers of purchase orders.
        This method ensures customer privacy by removing them from PO followers.
        
        :param customer_partner_ids: List of customer partner IDs to remove (if None, auto-detects)
        """
        self.ensure_one()
        
        if customer_partner_ids is None:
            customer_partner_ids = self._get_customer_partner_ids()
        
        if not customer_partner_ids:
            return
        
        try:
            # Get all followers of this purchase order
            followers = self.env['mail.followers'].search([
                ('res_model', '=', 'purchase.order'),
                ('res_id', '=', self.id),
                ('partner_id', 'in', customer_partner_ids),
            ])
            
            if followers:
                _logger.warning(
                    "🔒 PRIVACY FIX: Removing %d customer follower(s) from PO %s (customer IDs: %s)",
                    len(followers), self.name, customer_partner_ids
                )
                followers.unlink()
                
                # Also check message_follower_ids directly on the record
                customer_followers = self.message_follower_ids.filtered(
                    lambda f: f.partner_id.id in customer_partner_ids
                )
                if customer_followers:
                    self.message_unsubscribe(customer_partner_ids)
                    _logger.info(
                        "🔒 PRIVACY FIX: Unsubscribed %d customer partner(s) from PO %s",
                        len(customer_followers), self.name
                    )
        except Exception as e:
            _logger.error(
                "Error removing customer followers from PO %s: %s",
                self.name, str(e), exc_info=True
            )

    # ---------------------------------------------------------------
    # Mail gateway hooks
    # ---------------------------------------------------------------
    def message_update(self, msg_dict, update_vals=None):
        res = super().message_update(msg_dict, update_vals)
        try:
            self._message_receive_tracking(msg_dict)
            self._check_order_confirmation(msg_dict)
        except Exception as e:
            _logger.warning("Message processing failed in message_update: %s", e)
        return res

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        rec = super().message_new(msg_dict, custom_values=custom_values)
        try:
            rec._message_receive_tracking(msg_dict)
            rec._check_order_confirmation(msg_dict)
        except Exception as e:
            _logger.warning("Message processing failed in message_new: %s", e)
        return rec

    def _apply_tracking(self, tracking, msg_dict):
        """Attach tracking to related pickings and log.
        
        Validates tracking number with FedEx API and sends shipped email to customer.
        """
        pickings = self._get_related_pickings()
        if not pickings:
            return

        # Check for duplicate tracking number in other POs/pickings
        duplicate_info = self._check_duplicate_tracking(tracking)
        if duplicate_info:
            # Send email to supplier about duplicate tracking number
            self._send_duplicate_tracking_email(tracking, duplicate_info)
            self.message_post(
                body=_("❌ Duplicate tracking number rejected: <b>%s</b><br/>"
                       "This tracking number is already associated with %s.<br/>Supplier has been notified.")
                     % (tracking, duplicate_info)
            )
            return

        # Validate tracking number with FedEx API
        is_valid, validation_error = self._validate_tracking_number(tracking)
        if not is_valid:
            # Send email to supplier about invalid tracking number
            self._send_invalid_tracking_email(tracking, validation_error)
            self.message_post(
                body=_("❌ Invalid tracking number received: <b>%s</b><br/>Error: %s<br/>Supplier has been notified.")
                     % (tracking, validation_error or "Tracking number not found in FedEx system")
            )
            return

        # Tracking is valid, proceed with update
        for p in pickings:
            try:
                p.carrier_tracking_ref = tracking
                p.message_post(
                    body=_("✅ Tracking captured from supplier reply: <b>%s</b>") % tracking
                )
                # Send shipped email to customer
                self._send_order_shipped_email(p, tracking)
            except Exception as e:
                _logger.warning("Tracking update failed on picking %s: %s", p.name, e)

        self.tracking_last_seen = tracking
        self.tracking_last_seen_date = fields.Datetime.now()
        self.message_post(
            body=_("Auto-captured tracking from supplier email: <b>%s</b> (Validated with FedEx)") % tracking
        )

    # ---------------------------------------------------------------
    # Cron job: follow up with suppliers missing tracking numbers
    # ---------------------------------------------------------------
    @api.model
    def cron_followup_missing_tracking(self):
        """Send automatic reminders to suppliers who haven't provided tracking.
        
        Only processes POs approved after the configured minimum date to exclude
        existing/old orders from automatic reminders.
        
        REQUIRES: tracking_reminder_min_date must be configured in settings.
        """
        icp = self.env["ir.config_parameter"].sudo()
        max_rem = int(icp.get_param("ox_dropship_tracking_auto.max_reminders", "20"))

        now = fields.Datetime.now()
        
        # Get minimum approval date threshold (REQUIRED - no default)
        min_date_str = icp.get_param("ox_dropship_tracking_auto.tracking_reminder_min_date", "")
        
        if not min_date_str:
            # Date is REQUIRED - if not set, don't run the cron
            _logger.warning(
                "⚠️ Tracking reminder cron SKIPPED: 'Minimum PO Approval Date' is not configured. "
                "Please set the date in Settings > FedEx Integration to enable tracking reminders."
            )
            return
        
        # Date is set - parse it
        try:
            min_date = datetime.strptime(min_date_str, DEFAULT_SERVER_DATETIME_FORMAT)
            _logger.info("Using configured tracking_reminder_min_date: %s", min_date)
        except Exception as e:
            _logger.error(
                "❌ Tracking reminder cron FAILED: Invalid tracking_reminder_min_date format: %s - %s. "
                "Please configure a valid date in Settings > FedEx Integration.",
                min_date_str, e
            )
            return

        # Build domain: Only POs approved on/after configured date
        # No waiting period - reminders sent immediately for POs approved on/after min_date
        domain = [
            ("state", "in", ["purchase", "done"]),
            ("date_approve", ">=", min_date),  # Only POs approved on/after configured date
        ]
        
        _logger.info(
            "🔍 Searching for POs: approved on or after %s (no waiting period)", 
            min_date
        )
        orders = self.search(domain)
        for po in orders:
            picks = po._get_related_pickings()
            # Skip if already has valid tracking number
            if picks and any(p.carrier_tracking_ref for p in picks):
                continue
            
            # Check if we've reached 20 reminders and still no tracking
            reminder_count = po.tracking_reminder_count or 0
            if reminder_count >= max_rem:
                # Send notification to company if not already notified
                if not po.tracking_reminder_company_notified:
                    po._send_max_reminders_company_notification()
                    po.tracking_reminder_company_notified = True
                # Continue sending reminders (don't stop at 20)
            
            # No daily limit - can send reminders anytime

            try:
                # prepare email data
                template = self.env.ref(
                    "ox_dropship_tracking_auto.email_template_tracking_reminder",
                    raise_if_not_found=False,
                )
                if not template:
                    _logger.warning("Template email_template_tracking_reminder not found.")
                    continue

                email_from = (
                    po.user_id.email_formatted
                    or po.company_id.email
                    or self.env.user.email_formatted
                )
                reply_to = po.company_id.catchall_email or email_from

                # CRITICAL PRIVACY FIX: Remove customer followers BEFORE sending email
                # The message_subscribe override will prevent new additions, but clean up any existing ones
                po._remove_customer_followers()

                # use new mail.compose.message API (Odoo 18)
                Compose = self.env["mail.compose.message"].with_context({
                    "default_model": "purchase.order",
                    "default_res_ids": [po.id],
                    "default_use_template": True,
                    "default_template_id": template.id,
                    "default_composition_mode": "comment",
                    "default_email_from": email_from,
                    "default_reply_to": reply_to,
                })
                # CRITICAL: Explicitly set partner_ids to ONLY vendor to prevent customer followers
                compose = Compose.create({
                    "partner_ids": [(6, 0, [po.partner_id.id])],
                })
                compose.action_send_mail()

                # CRITICAL PRIVACY FIX: Safety net - remove any customer followers that might have been added
                # The message_subscribe override should prevent this, but this is a final safety check
                po._remove_customer_followers()

                po.tracking_reminder_last = now
                po.tracking_reminder_count += 1
                reminder_num = po.tracking_reminder_count
                
                if reminder_num >= max_rem:
                    po.message_post(
                        body=_("🔔 Threaded tracking reminder #%s sent to supplier. "
                               "⚠️ Maximum reminder threshold (%s) reached - company notified.") 
                        % (reminder_num, max_rem)
                    )
                else:
                    po.message_post(body=_("🔔 Threaded tracking reminder #%s sent to supplier.") % reminder_num)

                _logger.info("Threaded tracking reminder #%s sent for %s", reminder_num, po.name)

            except Exception as e:
                _logger.error("Failed to send threaded tracking reminder for %s: %s", po.name, e)
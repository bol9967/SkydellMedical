# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime

from odoo import api, fields, models, _
from dateutil import parser
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, float_is_zero

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    tracking_status = fields.Char(string="Tracking Status", copy=False, readonly=True)
    tracking_last_event = fields.Char(string="Last Tracking Event", copy=False, readonly=True)
    tracking_last_date = fields.Datetime(string="Last Tracking Update", copy=False, readonly=True)
    tracking_raw = fields.Text(string="Tracking Raw JSON", copy=False, readonly=True)
    fedex_last_check = fields.Datetime(string="Last FedEx Check", copy=False, readonly=True)
    fedex_delivered = fields.Boolean(string="Delivered (FedEx)", copy=False, readonly=True)
    fedex_delivered_notified = fields.Boolean(string="Customer Notified on Delivery", copy=False, readonly=True)
    fedex_auto_validated = fields.Boolean(string="Auto-Validated from FedEx", copy=False, readonly=True)

    # ------------------------------------------------------------------
    # Extra fields to reflect *all* useful data from FedEx API response
    # ------------------------------------------------------------------
    fedex_tracking_number = fields.Char(string="FedEx Tracking #", copy=False, readonly=True)

    # Shipper information
    fedex_shipper_city = fields.Char(string="Shipper City", copy=False, readonly=True)
    fedex_shipper_state = fields.Char(string="Shipper State", copy=False, readonly=True)
    fedex_shipper_country = fields.Char(string="Shipper Country", copy=False, readonly=True)

    # Recipient information
    fedex_recipient_city = fields.Char(string="Recipient City", copy=False, readonly=True)
    fedex_recipient_state = fields.Char(string="Recipient State", copy=False, readonly=True)
    fedex_recipient_country = fields.Char(string="Recipient Country", copy=False, readonly=True)

    # Delivery details (actual delivery)
    fedex_delivery_city = fields.Char(string="Delivery City", copy=False, readonly=True)
    fedex_delivery_state = fields.Char(string="Delivery State", copy=False, readonly=True)
    fedex_delivery_country = fields.Char(string="Delivery Country", copy=False, readonly=True)
    fedex_delivery_location_type = fields.Char(string="Delivery Location Type", copy=False, readonly=True)
    fedex_delivery_location_desc = fields.Char(string="Delivery Location Description", copy=False, readonly=True)
    fedex_delivery_attempts = fields.Integer(string="Delivery Attempts", copy=False, readonly=True)
    fedex_delivery_received_by = fields.Char(string="Received By", copy=False, readonly=True)

    # Service details
    fedex_service_type = fields.Char(string="Service Type", copy=False, readonly=True)
    fedex_service_desc = fields.Char(string="Service Description", copy=False, readonly=True)
    fedex_service_short = fields.Char(string="Service Short Code", copy=False, readonly=True)

    # Shipment possession
    fedex_possession_status = fields.Boolean(string="FedEx Possession Status", copy=False, readonly=True)

    # Package weight
    fedex_weight_lb = fields.Float(string="Package Weight (LB)", copy=False, readonly=True)
    fedex_weight_kg = fields.Float(string="Package Weight (KG)", copy=False, readonly=True)

    # Package dimensions
    fedex_pkg_length_in = fields.Float(string="Length (in)", copy=False, readonly=True)
    fedex_pkg_width_in = fields.Float(string="Width (in)", copy=False, readonly=True)
    fedex_pkg_height_in = fields.Float(string="Height (in)", copy=False, readonly=True)
    fedex_pkg_length_cm = fields.Float(string="Length (cm)", copy=False, readonly=True)
    fedex_pkg_width_cm = fields.Float(string="Width (cm)", copy=False, readonly=True)
    fedex_pkg_height_cm = fields.Float(string="Height (cm)", copy=False, readonly=True)

    # Origin / Destination summary
    fedex_origin_city = fields.Char(string="Origin City", copy=False, readonly=True)
    fedex_origin_state = fields.Char(string="Origin State", copy=False, readonly=True)
    fedex_origin_country = fields.Char(string="Origin Country", copy=False, readonly=True)

    fedex_destination_city = fields.Char(string="Destination City", copy=False, readonly=True)
    fedex_destination_state = fields.Char(string="Destination State", copy=False, readonly=True)
    fedex_destination_country = fields.Char(string="FedEx Destination Country", copy=False, readonly=True)

    fedex_last_dest_city = fields.Char(string="Last Updated Dest. City", copy=False, readonly=True)
    fedex_last_dest_state = fields.Char(string="Last Updated Dest. State", copy=False, readonly=True)
    fedex_last_dest_country = fields.Char(string="Last Updated Dest. Country", copy=False, readonly=True)

    # Transit eta window
    fedex_standard_transit_end = fields.Datetime(string="Std Transit ETA", copy=False, readonly=True)

    # Miscellaneous details
    fedex_goods_classification_code = fields.Char(string="Goods Classification Code", copy=False, readonly=True)

    fedex_available_images = fields.Text(string="Available Images", copy=False, readonly=True)
    fedex_special_handlings = fields.Text(string="Special Handlings", copy=False, readonly=True)
    fedex_notifications = fields.Text(string="Available Notifications", copy=False, readonly=True)

    # Full structured lists as JSON text (so nothing is lost)
    fedex_date_times_json = fields.Text(string="All Date/Time Records (JSON)", copy=False, readonly=True)
    fedex_scan_events_json = fields.Text(string="All Scan Events (JSON)", copy=False, readonly=True)
    fedex_delivery_options_json = fields.Text(string="Delivery Options (JSON)", copy=False, readonly=True)

    fedex_can_dispute_delivery = fields.Boolean(string="Can Dispute Delivery", copy=False, readonly=True)

    # Extra explicit datetime fields from dateAndTimes[]
    fedex_actual_delivery = fields.Datetime(string="FedEx Actual Delivery", copy=False, readonly=True)
    fedex_actual_pickup = fields.Datetime(string="FedEx Actual Pickup", copy=False, readonly=True)
    fedex_ship_date = fields.Datetime(string="FedEx Ship Date", copy=False, readonly=True)
    fedex_actual_tender = fields.Datetime(string="FedEx Actual Tender", copy=False, readonly=True)

    # -------------------------------------------------------------
    # Internal helper for safe float conversion
    # -------------------------------------------------------------
    def _fedex_safe_float(self, value):
        try:
            return float(value)
        except Exception:
            return False

    # -------------------------------------------------------------
    # FedEx JSON parsing – aligned exactly with your Postman sample
    # -------------------------------------------------------------
    def _fedex_parse_result(self, data):
        """
        Extract tracking summary from FedEx response
        (structure from your sample JSON).
        """
        try:
            result = data["output"]["completeTrackResults"][0]["trackResults"][0]

            latest_status = result.get("latestStatusDetail", {}) or {}
            status = latest_status.get("statusByLocale")
            description = latest_status.get("description")
            scan_loc = latest_status.get("scanLocation", {}) or {}

            # Tracking number info
            tinfo = result.get("trackingNumberInfo", {}) or {}
            tracking_number = tinfo.get("trackingNumber")

            # Shipper / recipient info
            shipper_addr = (result.get("shipperInformation") or {}).get("address") or {}
            recipient_addr = (result.get("recipientInformation") or {}).get("address") or {}

            # dateAndTimes[] – prefer ACTUAL_DELIVERY and extract individual types
            date_list = result.get("dateAndTimes", []) or []
            delivery_date = None
            actual_delivery = None
            actual_pickup = None
            ship_date = None
            actual_tender = None
            if date_list:
                preferred = next((d for d in date_list if d.get("type") == "ACTUAL_DELIVERY"), None)
                delivery_date = (preferred or date_list[0]).get("dateTime")

                # Extract specific FedEx datetime types
                for d in date_list:
                    dt_type = d.get("type")
                    dt_value = d.get("dateTime")
                    if dt_type == "ACTUAL_DELIVERY":
                        actual_delivery = dt_value
                    elif dt_type == "ACTUAL_PICKUP":
                        actual_pickup = dt_value
                    elif dt_type == "SHIP":
                        ship_date = dt_value
                    elif dt_type == "ACTUAL_TENDER":
                        actual_tender = dt_value

            # scanEvents[0] – latest scan event
            scan_events = result.get("scanEvents", []) or []
            latest_scan = scan_events[0] if scan_events else {}

            latest_scan_desc = latest_scan.get("eventDescription")
            latest_scan_date = latest_scan.get("date")
            latest_scan_city = (latest_scan.get("scanLocation") or {}).get("city")
            latest_scan_state = (latest_scan.get("scanLocation") or {}).get("stateOrProvinceCode")

            # Available images
            available_images = result.get("availableImages", []) or []
            available_images_list = [img.get("type") for img in available_images if img.get("type")]

            # Special handlings
            special_handlings = result.get("specialHandlings", []) or []
            special_handlings_list = []
            for sh in special_handlings:
                stype = sh.get("type") or ""
                sdesc = sh.get("description") or ""
                spay = sh.get("paymentType") or ""
                special_handlings_list.append("%s - %s (payment: %s)" % (stype, sdesc, spay))

            # Package details (weight & dimensions)
            pkg = result.get("packageDetails", {}) or {}
            wdim = pkg.get("weightAndDimensions", {}) or {}
            weights = wdim.get("weight", []) or []
            dims = wdim.get("dimensions", []) or []

            weight_lb = False
            weight_kg = False
            for w in weights:
                unit = w.get("unit")
                val = w.get("value")
                if unit == "LB":
                    weight_lb = self._fedex_safe_float(val)
                elif unit == "KG":
                    weight_kg = self._fedex_safe_float(val)

            length_in = width_in = height_in = False
            length_cm = width_cm = height_cm = False
            for d in dims:
                units = d.get("units")
                l = d.get("length")
                w = d.get("width")
                h = d.get("height")
                if units == "IN":
                    length_in = self._fedex_safe_float(l)
                    width_in = self._fedex_safe_float(w)
                    height_in = self._fedex_safe_float(h)
                elif units == "CM":
                    length_cm = self._fedex_safe_float(l)
                    width_cm = self._fedex_safe_float(w)
                    height_cm = self._fedex_safe_float(h)

            # Shipment details
            shipment_details = result.get("shipmentDetails", {}) or {}
            possession_status = bool(shipment_details.get("possessionStatus"))

            # Service detail
            service_detail = result.get("serviceDetail", {}) or {}
            service_type = service_detail.get("type")
            service_desc = service_detail.get("description")
            service_short = service_detail.get("shortDescription")

            # Delivery details
            delivery_details = result.get("deliveryDetails", {}) or {}
            actual_delivery_address = delivery_details.get("actualDeliveryAddress") or {}
            delivery_city = actual_delivery_address.get("city")
            delivery_state = actual_delivery_address.get("stateOrProvinceCode")
            delivery_country = actual_delivery_address.get("countryName")

            delivery_location_type = delivery_details.get("locationType")
            delivery_location_desc = delivery_details.get("locationDescription")
            delivery_attempts = delivery_details.get("deliveryAttempts")
            received_by = delivery_details.get("receivedByName")

            # Delivery options
            delivery_options = delivery_details.get("deliveryOptionEligibilityDetails", []) or []
            can_dispute_delivery = any(
                (opt.get("option") == "DISPUTE_DELIVERY" and opt.get("eligibility") in ("ELIGIBLE", "POSSIBLY_ELIGIBLE"))
                for opt in delivery_options
            )

            # Origin / destination / last-updated-destination
            origin_loc = result.get("originLocation", {}) or {}
            origin_addr = (origin_loc.get("locationContactAndAddress") or {}).get("address") or {}
            origin_city = origin_addr.get("city")
            origin_state = origin_addr.get("stateOrProvinceCode")
            origin_country = origin_addr.get("countryName")

            dest_loc = result.get("destinationLocation", {}) or {}
            dest_addr = (dest_loc.get("locationContactAndAddress") or {}).get("address") or {}
            dest_city = dest_addr.get("city")
            dest_state = dest_addr.get("stateOrProvinceCode")
            dest_country = dest_addr.get("countryName")

            last_dest_addr = result.get("lastUpdatedDestinationAddress") or {}
            last_dest_city = last_dest_addr.get("city")
            last_dest_state = last_dest_addr.get("stateOrProvinceCode")
            last_dest_country = last_dest_addr.get("countryName")

            # Standard transit time window
            std_transit = result.get("standardTransitTimeWindow", {}) or {}
            std_window = std_transit.get("window") or {}
            std_transit_end = std_window.get("ends")

            # Goods classification
            goods_classification_code = result.get("goodsClassificationCode") or ""

            # Available notifications
            notifications = result.get("availableNotifications", []) or []
            notifications_list = notifications[:] if isinstance(notifications, list) else [notifications]

            return {
                # Existing summary info
                "status": status,
                "status_description": description,
                "delivery_date": delivery_date,
                "latest_scan_event": latest_scan_desc,
                "latest_scan_date": latest_scan_date,
                "latest_scan_city": latest_scan_city,
                "latest_scan_state": latest_scan_state,

                # Explicit dateAndTimes split
                "actual_delivery": actual_delivery,
                "actual_pickup": actual_pickup,
                "ship_date": ship_date,
                "actual_tender": actual_tender,

                # New: high-level tracking
                "tracking_number": tracking_number,

                # Shipper / recipient
                "shipper_city": shipper_addr.get("city"),
                "shipper_state": shipper_addr.get("stateOrProvinceCode"),
                "shipper_country": shipper_addr.get("countryName") or shipper_addr.get("countryCode"),
                "recipient_city": recipient_addr.get("city"),
                "recipient_state": recipient_addr.get("stateOrProvinceCode"),
                "recipient_country": recipient_addr.get("countryName") or recipient_addr.get("countryCode"),

                # Delivery details
                "delivery_city": delivery_city,
                "delivery_state": delivery_state,
                "delivery_country": delivery_country,
                "delivery_location_type": delivery_location_type,
                "delivery_location_desc": delivery_location_desc,
                "delivery_attempts": delivery_attempts,
                "delivery_received_by": received_by,

                # Service details
                "service_type": service_type,
                "service_desc": service_desc,
                "service_short": service_short,

                # Shipment possession
                "possession_status": possession_status,

                # Weights
                "weight_lb": weight_lb,
                "weight_kg": weight_kg,

                # Dimensions
                "length_in": length_in,
                "width_in": width_in,
                "height_in": height_in,
                "length_cm": length_cm,
                "width_cm": width_cm,
                "height_cm": height_cm,

                # Origin / destination
                "origin_city": origin_city,
                "origin_state": origin_state,
                "origin_country": origin_country,
                "destination_city": dest_city,
                "destination_state": dest_state,
                "destination_country": dest_country,
                "last_dest_city": last_dest_city,
                "last_dest_state": last_dest_state,
                "last_dest_country": last_dest_country,

                # Transit ETA
                "std_transit_end": std_transit_end,

                # Misc
                "goods_classification_code": goods_classification_code,

                # Lists / JSON blobs
                "available_images": available_images_list,
                "special_handlings": special_handlings_list,
                "notifications": notifications_list,
                "date_times_json": json.dumps(date_list, default=str),
                "scan_events_json": json.dumps(scan_events, default=str),
                "delivery_options_json": json.dumps(delivery_options, default=str),
                "can_dispute_delivery": can_dispute_delivery,
            }
        except Exception as e:
            _logger.error("FedEx parse error: %s | data=%s", e, json.dumps(data, default=str)[:1000])
            return {}

    # -------------------------------------------------------------
    # Helper: determine recipient + context for delivery email
    # -------------------------------------------------------------
    def _fedex_get_delivery_recipient(self):
        """
        For dropship pickings:
          - Use the related sale order shipping address (or SO customer)
        For normal outgoing:
          - Use picking.partner_id (customer)
        Returns (partner, email_to, lang)
        """
        self.ensure_one()

        partner = False
        email_to = False
        lang = False

        if self.picking_type_code == "dropship":
            sale = self.sale_id
            if sale:
                partner = sale.partner_shipping_id or sale.partner_id or self.partner_id
            else:
                # Fallback if for some reason no sale_id
                partner = self.partner_id
        else:
            partner = self.partner_id

        if partner:
            email_to = partner.email or False
            lang = partner.lang or self.env.user.lang
        else:
            lang = self.env.user.lang

        return partner, email_to, lang

    # -------------------------------------------------------------
    # Send delivery validated notification to company
    # -------------------------------------------------------------
    def _send_delivery_validated_email(self):
        """Send email to orders@skydellmedical.com notifying that delivery was auto-validated."""
        self.ensure_one()
        
        try:
            # Send to specific email address
            company_email = "orders@skydellmedical.com"
            
            # Get email template
            template = self.env.ref(
                "ox_dropship_tracking_auto.email_template_delivery_validated",
                raise_if_not_found=False,
            )
            if not template:
                _logger.warning("Email template email_template_delivery_validated not found.")
                return
            
            # Send email using template
            email_values = {"email_to": company_email}
            
            template.with_context(lang=self.env.user.lang).send_mail(
                self.id, force_send=True, email_values=email_values
            )
            
            _logger.info(
                "Delivery validated notification sent to %s for picking %s (type=%s)",
                company_email,
                self.name,
                self.picking_type_code,
            )
            
        except Exception as e:
            _logger.error("Failed to send delivery validated email for picking %s: %s", self.name, e)

    # -------------------------------------------------------------
    # Create and post vendor bill after delivery validation
    # -------------------------------------------------------------
    def _create_and_post_vendor_bill(self):
        """Create and post vendor bill for the related purchase order after delivery validation."""
        self.ensure_one()
        
        try:
            # Find the purchase order from picking origin
            purchase_order = False
            if self.origin:
                purchase_order = self.env["purchase.order"].sudo().search([
                    ("name", "=", self.origin)
                ], limit=1)
            
            # If not found by origin, try to find through move lines
            if not purchase_order:
                purchase_moves = self.move_ids.filtered(lambda m: m.purchase_line_id)
                if purchase_moves:
                    purchase_order = purchase_moves[0].purchase_line_id.order_id
            
            if not purchase_order:
                _logger.info(
                    "No purchase order found for picking %s - skipping bill creation",
                    self.name
                )
                return
            
            # Check if PO is in a valid state for invoicing
            if purchase_order.state not in ("purchase", "done"):
                _logger.info(
                    "Purchase order %s is in state '%s' - not eligible for bill creation",
                    purchase_order.name,
                    purchase_order.state
                )
                return
            
            # Check if invoice already exists and is posted
            posted_bills = purchase_order.invoice_ids.filtered(
                lambda inv: inv.state == "posted" and inv.move_type == "in_invoice"
            )
            if posted_bills:
                _logger.info(
                    "Purchase order %s already has posted bill(s): %s - skipping bill creation",
                    purchase_order.name,
                    ", ".join(posted_bills.mapped("name"))
                )
                return
            
            # Check if there are invoiceable lines
            if purchase_order.invoice_status == "invoiced":
                _logger.info(
                    "Purchase order %s is already fully invoiced - skipping bill creation",
                    purchase_order.name
                )
                return
            
            # Store existing invoice IDs before creation
            existing_invoice_ids = purchase_order.invoice_ids.ids
            
            # Create the bill
            _logger.info(
                "Creating vendor bill for purchase order %s (picking: %s)",
                purchase_order.name,
                self.name
            )
            
            # Call action_create_invoice which returns an action dict
            try:
                action_result = purchase_order.action_create_invoice()
            except Exception as e:
                _logger.error(
                    "Failed to create bill for purchase order %s: %s",
                    purchase_order.name,
                    e
                )
                return
            
            # Refresh to get newly created invoices
            purchase_order.invalidate_recordset(['invoice_ids'])
            purchase_order = purchase_order.browse(purchase_order.id)
            
            # Find newly created draft invoices
            new_invoices = purchase_order.invoice_ids.filtered(
                lambda inv: inv.id not in existing_invoice_ids 
                and inv.move_type == "in_invoice" 
                and inv.state == "draft"
            )
            
            if not new_invoices:
                _logger.warning(
                    "No new draft bills created for purchase order %s (picking: %s)",
                    purchase_order.name,
                    self.name
                )
                return
            
            # Post the bill(s)
            for invoice in new_invoices:
                if invoice.state == "draft" and invoice.move_type == "in_invoice":
                    try:
                        # Set invoice date before posting (required for validation)
                        # Use today's date as the bill date - write explicitly to ensure it's saved
                        bill_date = fields.Date.today()
                        
                        _logger.info(
                            "Setting invoice_date for bill %s (PO %s, picking %s): current_date=%s, bill_date=%s",
                            invoice.name or "Draft",
                            purchase_order.name,
                            self.name,
                            invoice.invoice_date,
                            bill_date
                        )
                        
                        # Always set the invoice_date, even if it exists (to ensure it's today's date)
                        invoice.sudo().write({'invoice_date': bill_date})
                        
                        # Refresh to ensure the date is set
                        invoice.invalidate_recordset(['invoice_date'])
                        invoice = invoice.browse(invoice.id)
                        
                        # Verify invoice_date is set before posting
                        if not invoice.invoice_date:
                            _logger.error(
                                "❌ Invoice date still not set for bill %s after write attempt. "
                                "This may cause posting to fail.",
                                invoice.name or "Draft"
                            )
                            # Try one more time with direct assignment
                            invoice.invoice_date = bill_date
                            invoice.flush_recordset(['invoice_date'])
                        
                        _logger.info(
                            "Invoice date set successfully for bill %s: invoice_date=%s",
                            invoice.name or "Draft",
                            invoice.invoice_date
                        )
                        
                        invoice.action_post()
                        _logger.info(
                            "✅ Vendor bill %s created and posted for purchase order %s (picking: %s)",
                            invoice.name,
                            purchase_order.name,
                            self.name
                        )
                        
                        # Post message to purchase order chatter
                        tracking_info = ""
                        if self.fedex_tracking_number:
                            tracking_info = _(" (FedEx Tracking: %s)") % self.fedex_tracking_number
                        purchase_order.message_post(
                            body=_("✅ Vendor bill %s created and posted automatically after delivery validation based on FedEx 'Delivered' status.%s\n\nDelivery: %s") % (
                                invoice.name,
                                tracking_info,
                                self.name
                            )
                        )
                        
                        # Post message to bill chatter
                        invoice.message_post(
                            body=_("✅ This bill was automatically created and posted based on FedEx 'Delivered' status.\n\nPurchase Order: %s\nDelivery: %s%s") % (
                                purchase_order.name,
                                self.name,
                                tracking_info
                            )
                        )
                    except Exception as e:
                        _logger.error(
                            "Failed to post vendor bill %s for purchase order %s: %s",
                            invoice.name,
                            purchase_order.name,
                            e
                        )
                        # Post error message to purchase order chatter
                        purchase_order.message_post(
                            body=_("⚠️ Vendor bill %s was created but could not be posted automatically: %s") % (invoice.name, str(e))
                        )
                else:
                    _logger.info(
                        "Bill %s is in state '%s' - skipping post (picking: %s)",
                        invoice.name,
                        invoice.state,
                        self.name
                    )
                    
        except Exception as e:
            _logger.error(
                "Failed to create/post vendor bill for picking %s: %s",
                self.name,
                e
            )

    # -------------------------------------------------------------
    # Simple datetime normalizer: strip timezone and "T"
    # -------------------------------------------------------------
    def _fedex_to_odoo_dt(self, dt_str):
        """
        Safe ISO8601 datetime → Odoo datetime converter for Odoo 18
        Handles timezone, offsets, and returns UTC.
        """
        if not dt_str:
            return False
        try:
            # Parse ISO8601 datetime with timezone
            dt = parser.isoparse(dt_str)

            # Convert to UTC (Odoo stores UTC in database)
            dt_utc = dt.astimezone(tz=None).strftime(DEFAULT_SERVER_DATETIME_FORMAT)
            return dt_utc
        except Exception as e:
            _logger.error("FedEx datetime parse failed: %s | %s", dt_str, e)
            return False

    # -------------------------------------------------------------
    # Cron: update tracking & send delivered email
    # -------------------------------------------------------------
    @api.model
    def _cron_update_fedex_tracking(self):
        """
        Periodically check FedEx for deliveries that have a tracking
        number and update status. If 'Delivered' and not yet notified, send
        customer email.

        Applies to:
          - Normal outgoing deliveries (picking_type_code = 'outgoing')
          - Dropship deliveries (picking_type_code = 'dropship')
        
        Only processes pickings created on/after configured minimum date.
        Skips pickings already marked as delivered.
        """
        FedexAPI = self.env["fedex.api"]
        
        # Get minimum date for FedEx tracking (REQUIRED)
        # If date is empty or not set, API will not do any action until date is set
        icp = self.env["ir.config_parameter"].sudo()
        min_date_str = icp.get_param("ox_dropship_tracking_auto.fedex_tracking_min_date", "")
        
        if not min_date_str or min_date_str.strip() == "":
            _logger.warning(
                "⚠️ FedEx tracking cron SKIPPED: 'Minimum Date for FedEx API Tracking' is not configured. "
                "Please set the date in Settings > FedEx Integration to enable FedEx API tracking checks. "
                "No API calls will be made until this date is configured."
            )
            return
        
        try:
            min_date = datetime.strptime(min_date_str, DEFAULT_SERVER_DATETIME_FORMAT)
            _logger.info("Using configured fedex_tracking_min_date: %s", min_date)
        except Exception as e:
            _logger.error(
                "❌ FedEx tracking cron FAILED: Invalid fedex_tracking_min_date format: %s - %s. "
                "Please configure a valid date in Settings > FedEx Integration. "
                "No API calls will be made until a valid date is configured.",
                min_date_str, e
            )
            return

        domain = [
            ("picking_type_code", "in", ["outgoing", "dropship"]),
            ("carrier_tracking_ref", "!=", False),
            ("state", "!=", "cancel"),
            ("create_date", ">=", min_date),  # Only pickings created on/after configured date
            ("fedex_delivered", "=", False),  # Skip already delivered pickings
        ]
        pickings = self.search(domain)
        _logger.info("FedEx cron: found %s pickings to check (created on/after %s, not yet delivered)", 
                    len(pickings), min_date)

        for picking in pickings:
            tn = picking.carrier_tracking_ref
            if not tn:
                continue

            try:
                res = FedexAPI.track_shipment(tn)
            except Exception as e:
                _logger.error("FedEx tracking failed for %s (%s): %s", picking.name, tn, e)
                continue

            parsed = picking._fedex_parse_result(res)
            if not parsed:
                continue

            # ----------------------------------------------
            # Prepare values to write
            # ----------------------------------------------

            # tracking_last_date: prefer latest_scan_date, then delivery_date
            last_dt = parsed.get("latest_scan_date") or parsed.get("delivery_date")
            tracking_last_date = self._fedex_to_odoo_dt(last_dt)

            std_transit_end = self._fedex_to_odoo_dt(parsed.get("std_transit_end"))

            vals = {
                "tracking_status": parsed.get("status"),
                "tracking_last_event": parsed.get("latest_scan_event"),
                "tracking_raw": json.dumps(res, default=str),
                "fedex_last_check": fields.Datetime.now(),
                "fedex_tracking_number": parsed.get("tracking_number"),

                # tracking_last_date (converted)
                "tracking_last_date": tracking_last_date,

                # Shipper / Recipient
                "fedex_shipper_city": parsed.get("shipper_city"),
                "fedex_shipper_state": parsed.get("shipper_state"),
                "fedex_shipper_country": parsed.get("shipper_country"),
                "fedex_recipient_city": parsed.get("recipient_city"),
                "fedex_recipient_state": parsed.get("recipient_state"),
                "fedex_recipient_country": parsed.get("recipient_country"),

                # Delivery details
                "fedex_delivery_city": parsed.get("delivery_city"),
                "fedex_delivery_state": parsed.get("delivery_state"),
                "fedex_delivery_country": parsed.get("delivery_country"),
                "fedex_delivery_location_type": parsed.get("delivery_location_type"),
                "fedex_delivery_location_desc": parsed.get("delivery_location_desc"),
                "fedex_delivery_received_by": parsed.get("delivery_received_by"),

                # Attempts
                "fedex_delivery_attempts": int(parsed.get("delivery_attempts") or 0),

                # Service details
                "fedex_service_type": parsed.get("service_type"),
                "fedex_service_desc": parsed.get("service_desc"),
                "fedex_service_short": parsed.get("service_short"),

                # Shipment possession & weights
                "fedex_possession_status": parsed.get("possession_status"),
                "fedex_weight_lb": parsed.get("weight_lb"),
                "fedex_weight_kg": parsed.get("weight_kg"),

                # Dimensions
                "fedex_pkg_length_in": parsed.get("length_in"),
                "fedex_pkg_width_in": parsed.get("width_in"),
                "fedex_pkg_height_in": parsed.get("height_in"),
                "fedex_pkg_length_cm": parsed.get("length_cm"),
                "fedex_pkg_width_cm": parsed.get("width_cm"),
                "fedex_pkg_height_cm": parsed.get("height_cm"),

                # Origin / Destination
                "fedex_origin_city": parsed.get("origin_city"),
                "fedex_origin_state": parsed.get("origin_state"),
                "fedex_origin_country": parsed.get("origin_country"),
                "fedex_destination_city": parsed.get("destination_city"),
                "fedex_destination_state": parsed.get("destination_state"),
                "fedex_destination_country": parsed.get("destination_country"),

                # Last updated destination
                "fedex_last_dest_city": parsed.get("last_dest_city"),
                "fedex_last_dest_state": parsed.get("last_dest_state"),
                "fedex_last_dest_country": parsed.get("last_dest_country"),

                # Transit ETA (converted)
                "fedex_standard_transit_end": std_transit_end,

                # Misc
                "fedex_goods_classification_code": parsed.get("goods_classification_code"),
                "fedex_available_images": "\n".join(parsed.get("available_images") or []),
                "fedex_special_handlings": "\n".join(parsed.get("special_handlings") or []),
                "fedex_notifications": "\n".join(parsed.get("notifications") or []),
                "fedex_date_times_json": parsed.get("date_times_json"),
                "fedex_scan_events_json": parsed.get("scan_events_json"),
                "fedex_delivery_options_json": parsed.get("delivery_options_json"),
                "fedex_can_dispute_delivery": parsed.get("can_dispute_delivery", False),
            }

            # -------- DATETIME CONVERSION (Special handling) ---------
            if parsed.get("actual_delivery"):
                vals["fedex_actual_delivery"] = self._fedex_to_odoo_dt(parsed["actual_delivery"])

            if parsed.get("actual_pickup"):
                vals["fedex_actual_pickup"] = self._fedex_to_odoo_dt(parsed["actual_pickup"])

            if parsed.get("ship_date"):
                vals["fedex_ship_date"] = self._fedex_to_odoo_dt(parsed["ship_date"])

            if parsed.get("actual_tender"):
                vals["fedex_actual_tender"] = self._fedex_to_odoo_dt(parsed["actual_tender"])

            # WRITE ALL FIELDS AT ONCE (sudo to bypass readonly in UI)
            picking.sudo().write(vals)

            # ----------------------------------------------
            # Delivery detection + email + auto-validation
            # ----------------------------------------------
            if (parsed.get("status") or "").lower() == "delivered":
                picking.fedex_delivered = True

                # Auto-validate delivery if not already validated
                if not picking.fedex_auto_validated and picking.state not in ("done", "cancel"):
                    try:
                        # Check if picking can be validated
                        # Valid states: 'assigned' (Ready), 'waiting' (Waiting Another Operation), or 'confirmed' (Waiting)
                        # Note: "Ready" is the display name for state "assigned"
                        valid_states = ("assigned", "waiting", "confirmed")
                        if picking.state in valid_states:
                            # Store original state for logging
                            original_state = picking.state
                            
                            # Prepare moves for validation if needed
                            # For dropship pickings, we may need to ensure moves are ready
                            picking = picking.sudo()
                            
                            # Check if moves need preparation
                            moves_to_prepare = picking.move_ids.filtered(
                                lambda m: m.state in ('draft', 'confirmed', 'waiting')
                            )
                            if moves_to_prepare:
                                # Confirm moves that are in draft
                                draft_moves = moves_to_prepare.filtered(lambda m: m.state == 'draft')
                                if draft_moves:
                                    draft_moves._action_confirm()
                                
                                # Try to assign moves that are waiting/confirmed
                                waiting_moves = moves_to_prepare.filtered(
                                    lambda m: m.state in ('confirmed', 'waiting')
                                )
                                if waiting_moves:
                                    waiting_moves._action_assign()
                            
                            # Ensure move lines exist and have quantities set
                            # Following Odoo's button_validate logic
                            for move in picking.move_ids:
                                # Set move.quantity if it's zero (like button_validate does)
                                if float_is_zero(move.quantity, precision_rounding=move.product_uom.rounding) and\
                                   not float_is_zero(move.product_uom_qty, precision_rounding=move.product_uom.rounding):
                                    move.quantity = move.product_uom_qty
                                
                                # Ensure move lines exist
                                if not move.move_line_ids:
                                    # Try to assign first
                                    move._action_assign()
                                    if not move.move_line_ids:
                                        # If still no move lines, create one manually with quantity set
                                        self.env['stock.move.line'].create({
                                            'move_id': move.id,
                                            'product_id': move.product_id.id,
                                            'product_uom_id': move.product_uom.id,
                                            'location_id': move.location_id.id,
                                            'location_dest_id': move.location_dest_id.id,
                                            'quantity': move.product_uom_qty,  # Use 'quantity' not 'qty_done'
                                            'picked': True,  # Mark as picked
                                        })
                                else:
                                    # Set quantity on existing move lines if not set
                                    for ml in move.move_line_ids:
                                        if float_is_zero(ml.quantity, precision_rounding=ml.product_uom_id.rounding):
                                            ml.quantity = move.product_uom_qty
                                        if not ml.picked:
                                            ml.picked = True
                            
                            # Validate the picking - use _action_done() for direct validation
                            # This bypasses any wizards and validates immediately
                            picking._action_done()
                            
                            # Force refresh to get updated state from database
                            picking.invalidate_recordset(['state'])
                            picking = picking.browse(picking.id)  # Get fresh record
                            
                            # Check if validation was successful (state should be 'done')
                            if picking.state == "done":
                                picking.fedex_auto_validated = True
                                
                                # Send notification email to company ONLY after successful validation
                                picking._send_delivery_validated_email()
                                
                                # Create and post vendor bill if applicable
                                picking._create_and_post_vendor_bill()
                                
                                picking.message_post(
                                    body=_("✅ Delivery auto-validated based on FedEx 'Delivered' status. "
                                           "State changed from '%s' to 'done'.") % original_state
                                )
                                _logger.info(
                                    "✅ Delivery auto-validated for picking %s (type=%s, state: %s -> done) based on FedEx status",
                                    picking.name,
                                    picking.picking_type_code,
                                    original_state,
                                )
                            else:
                                # Validation didn't complete
                                _logger.warning(
                                    "⚠️ Validation attempted for picking %s but state is still '%s' (expected 'done'). "
                                    "Original state was '%s'.",
                                    picking.name,
                                    picking.state,
                                    original_state,
                                )
                                picking.message_post(
                                    body=_("⚠️ Auto-validation attempted but picking state is still '%s' (was '%s'). "
                                           "Validation may require manual confirmation.") % (picking.state, original_state)
                                )
                        else:
                            _logger.warning(
                                "Cannot auto-validate picking %s: state is '%s' (expected one of: %s)",
                                picking.name,
                                picking.state,
                                valid_states,
                            )
                            picking.message_post(
                                body=_("⚠️ Cannot auto-validate: picking state '%s' is not valid for validation. "
                                       "Expected: %s") % (picking.state, ", ".join(valid_states))
                            )
                    except Exception as e:
                        _logger.error(
                            "Failed to auto-validate delivery for picking %s: %s", picking.name, e
                        )
                        picking.message_post(
                            body=_("⚠️ Auto-validation failed: %s") % str(e)
                        )

                if not picking.fedex_delivered_notified:
                    partner, email_to, lang = picking._fedex_get_delivery_recipient()

                    if not email_to:
                        _logger.warning(
                            "FedEx delivered for %s but no email recipient found (dropship=%s)",
                            picking.name,
                            picking.picking_type_code == "dropship",
                        )
                        continue

                    template = self.env.ref(
                        "ox_dropship_tracking_auto.email_template_fedex_delivery_notification",
                        raise_if_not_found=False,
                    )
                    if template:
                        try:
                            # Use only email_to to avoid adding customer as follower to picking
                            email_values = {"email_to": email_to}

                            template.with_context(lang=lang).send_mail(
                                picking.id, force_send=True, email_values=email_values
                            )
                            picking.fedex_delivered_notified = True

                            picking.message_post(
                                body=_(
                                    "📦 FedEx Update: Shipment delivered. "
                                    "Customer (%s) notified by email."
                                )
                                % (partner.display_name if partner else email_to)
                            )
                            _logger.info(
                                "FedEx delivered email sent to %s for picking %s (type=%s)",
                                email_to,
                                picking.name,
                                picking.picking_type_code,
                            )
                        except Exception as e:
                            _logger.error("Failed to send FedEx delivered email for %s: %s", picking.name, e)


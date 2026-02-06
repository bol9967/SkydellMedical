# -*- coding: utf-8 -*-
from odoo import models, api, fields
import logging
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    dropship_auto_email_processed = fields.Boolean(
        string='Dropship Auto Email Processed',
        default=False,
        copy=False,
        help='Flag to ensure dropship PO sends only one automatic vendor email'
    )

    def _copy_carrier_from_sale_order(self):
        """
        Add delivery line to purchase order with the same cost as the sale order delivery.
        This ensures the vendor sees the shipping cost that the customer paid.
        """
        for po in self:
            # Get all purchase order lines that have a sale line
            po_lines_with_sale = po.order_line.filtered('sale_line_id')
            
            if not po_lines_with_sale:
                _logger.debug("No purchase order lines with sale_line_id found for PO %s, skipping delivery line", po.name)
                continue
            
            # Get sale orders from purchase order lines
            sale_orders = po_lines_with_sale.mapped('sale_line_id.order_id')
            
            if not sale_orders:
                _logger.debug("No sale orders found for PO %s, skipping delivery line", po.name)
                continue
            
            # Add delivery line to PO (only once per PO, not per line)
            # Check if delivery line already exists (check by delivery product or name containing "Delivery")
            delivery_product_ref = self.env.ref("delivery.product_product_delivery", raise_if_not_found=False)
            existing_delivery = po.order_line.filtered(
                lambda l: (delivery_product_ref and l.product_id.id == delivery_product_ref.id) 
                or "Delivery" in (l.name or "").lower()
            )
            if existing_delivery:
                _logger.debug("PO %s already has delivery line(s), skipping", po.name)
                continue
            
            # Get delivery line from sale order (use first sale order found)
            sale_order = sale_orders[0]
            delivery_line = sale_order.order_line.filtered(lambda l: getattr(l, 'is_delivery', False))
            
            if not delivery_line:
                _logger.debug("No delivery line found on sale order %s, skipping delivery line creation for PO %s", sale_order.name, po.name)
                continue
            
            delivery_line = delivery_line[0]  # Get first delivery line
            delivery_cost = delivery_line.price_unit
            
            if delivery_cost <= 0:
                _logger.debug("Delivery cost is 0 or negative on sale order %s, skipping delivery line creation for PO %s", sale_order.name, po.name)
                continue
            
            try:
                # Get or create delivery product
                delivery_product = sale_order.carrier_id.product_id if sale_order.carrier_id else None
                if not delivery_product:
                    delivery_product = self.env.ref("delivery.product_product_delivery", raise_if_not_found=False)
                if not delivery_product:
                    # Create a delivery product if it doesn't exist
                    delivery_product = self.env["product.product"].create({
                        "name": "Delivery",
                        "type": "service",
                        "purchase_ok": True,
                        "sale_ok": False,
                        "list_price": 0.0,
                    })
                
                # Create delivery line on purchase order
                po.order_line.create({
                    "order_id": po.id,
                    "name": delivery_line.name or (sale_order.carrier_id.name if sale_order.carrier_id else "Delivery"),
                    "product_id": delivery_product.id,
                    "product_qty": 1,
                    "product_uom": delivery_product.uom_id.id,
                    "price_unit": delivery_cost,
                    "date_planned": po.date_order or datetime.now(),
                })
                
                _logger.info("✅ Successfully added delivery line to PO %s with cost %s (from sale order %s)", 
                           po.name, delivery_cost, sale_order.name)
                
            except Exception as e:
                _logger.error("❌ Error creating delivery line on PO %s: %s", po.name, str(e), exc_info=True)

    def auto_confirm_and_notify_vendor(self):
        """
        Confirm PO + Send Email to Vendor automatically using native mail composer.
        
        This method is IDEMPOTENT - it can be called multiple times safely.
        It will only send ONE email per PO, regardless of how many times it's called.
        """
        for po in self:
            try:
                # Add delivery line from sale order to PO
                po._copy_carrier_from_sale_order()
                
                # IDEMPOTENCY CHECK: If already processed, skip (but still confirm if needed)
                # Refresh the record to ensure we have the latest flag value from database
                po.invalidate_recordset(['dropship_auto_email_processed'])
                if po.dropship_auto_email_processed:
                    _logger.info("PO %s already processed (dropship_auto_email_processed=True), skipping email (idempotency check)", po.name)
                    # Still confirm the PO if it's not confirmed yet (safe to call multiple times)
                    if po.state in ('draft', 'sent'):
                        po.button_confirm()
                        self.env.flush_all()
                    continue

                # First confirm the PO (if not already confirmed)
                if po.state in ('draft', 'sent'):
                    po.button_confirm()
                    # Flush to ensure state is saved
                    self.env.flush_all()
                    _logger.info("Auto-confirmed Purchase Order: %s", po.name)

                # Only send email if PO is confirmed (purchase state)
                if po.state != 'purchase':
                    _logger.warning("Purchase Order %s not in 'purchase' state (current: %s). Skipping email.", po.name, po.state)
                    continue

                # Check if vendor has email
                if not po.partner_id.email:
                    _logger.warning("No email address found for vendor partner %s (PO: %s). Skipping email.", po.partner_id.name, po.name)
                    # Mark as processed even without email to prevent retries
                    po.dropship_auto_email_processed = True
                    po.flush_recordset(['dropship_auto_email_processed'])
                    continue

                # Additional safety check: Verify no recent email was sent (backup check)
                recent_cutoff = datetime.now() - timedelta(seconds=120)
                
                # Check mail.mail records
                existing_mails = self.env['mail.mail'].search([
                    ('model', '=', 'purchase.order'),
                    ('res_id', '=', po.id),
                    '|',
                    ('email_to', 'ilike', po.partner_id.email),
                    ('partner_ids', 'in', [po.partner_id.id]),
                    ('create_date', '>=', recent_cutoff),
                    ('state', '!=', 'cancel'),
                ], limit=1)
                
                # Check message_ids in chatter
                recent_email = po.message_ids.filtered(
                    lambda m: (
                        m.message_type == 'email' 
                        and po.partner_id.id in m.partner_ids.ids
                        and m.create_date >= recent_cutoff
                    )
                )
                
                if existing_mails or recent_email:
                    _logger.info("PO %s already has recent email (mail.mail: %s, messages: %s), marking as processed", 
                               po.name, len(existing_mails), len(recent_email))
                    # Mark as processed to prevent future attempts
                    po.dropship_auto_email_processed = True
                    po.flush_recordset(['dropship_auto_email_processed'])
                    continue

                # Use PO confirmation template (not RFQ template)
                template = self.env.ref('purchase.email_template_edi_purchase_done', raise_if_not_found=False)
                if not template:
                    _logger.error("Email template 'purchase.email_template_edi_purchase_done' not found!")
                    continue

                _logger.info("Sending PO confirmation email for %s to %s", po.name, po.partner_id.email)
                
                # Use native mail composer mechanism (similar to action_rfq_send) for proper chatter recording
                try:
                    # Create mail composer context (same as action_rfq_send uses)
                    # Note: Odoo 18 uses 'default_res_ids' (plural) instead of 'default_res_id'
                    ctx = {
                        'default_model': 'purchase.order',
                        'default_res_ids': [po.id],  # Use list for Odoo 18
                        'default_use_template': bool(template.id),
                        'default_template_id': template.id,
                        'default_composition_mode': 'comment',
                        'mark_po_as_sent': True,
                        'custom_layout': 'mail.mail_notification_light',
                        'force_email': True,
                    }
                    
                    # Create mail composer with template
                    # Note: Template is auto-rendered on create, no need to call onchange
                    composer = self.env['mail.compose.message'].with_context(ctx)
                    composer_wizard = composer.create({
                        'model': 'purchase.order',
                        'res_ids': [po.id],  # Use list for Odoo 18
                        'template_id': template.id,
                        'composition_mode': 'comment',
                    })
                    
                    # Send the email (this will properly record in chatter like action_rfq_send)
                    # Template is already rendered automatically when composer is created
                    composer_wizard._action_send_mail()
                    
                    # Mark as processed IMMEDIATELY after sending to prevent duplicates
                    po.dropship_auto_email_processed = True
                    po.flush_recordset(['dropship_auto_email_processed'])
                    
                    _logger.info("PO confirmation email sent for %s to %s (recorded in chatter, marked as processed)", po.name, po.partner_id.email)
                    
                except Exception as e:
                    _logger.error("Error sending email via mail composer: %s", str(e), exc_info=True)
                    # Fallback: try direct template send
                    try:
                        mail_id = template.send_mail(po.id, force_send=True)
                        if mail_id:
                            mail = self.env['mail.mail'].browse(mail_id)
                            if mail.exists():
                                mail.write({'auto_delete': False})
                                mail.send()
                            # Mark as processed even if fallback succeeds
                            po.dropship_auto_email_processed = True
                            po.flush_recordset(['dropship_auto_email_processed'])
                            _logger.info("Email sent via fallback method for PO: %s (marked as processed)", po.name)
                    except Exception as fallback_error:
                        _logger.error("Fallback email send also failed: %s", str(fallback_error))
                        # Don't mark as processed if both methods failed - allow retry
                        
            except Exception as e:
                _logger.error("Error auto-confirming and notifying vendor for PO %s: %s", po.name, str(e), exc_info=True)

    @api.model
    def process_draft_pos_for_paid_orders(self):
        """
        Process draft purchase orders for sale orders that have paid transactions.
        This is a fallback method to handle cases where _set_done didn't catch the POs.
        """
        # Find all sale orders with done transactions
        txs = self.env['payment.transaction'].search([('state', '=', 'done')])
        paid_sale_orders = txs.mapped('sale_order_ids')
        
        if not paid_sale_orders:
            return
        
        # Find dropship route
        dropship_route = self.env['stock.route'].search([('name', 'ilike', 'dropship')], limit=1)
        if not dropship_route:
            return
        
        # Find all draft/sent POs linked to dropship lines of paid orders
        processed = 0
        for so in paid_sale_orders:
            dropship_lines = so.order_line.filtered(
                lambda l: (
                    (l.route_id and l.route_id.id == dropship_route.id)
                    or (dropship_route in l.product_id.route_ids)
                    or (l.product_id.categ_id and dropship_route in l.product_id.categ_id.route_ids)
                )
            )
            
            if dropship_lines:
                po_lines = self.env['purchase.order.line'].search([
                    ('sale_line_id', 'in', dropship_lines.ids)
                ])
                draft_pos = po_lines.mapped('order_id').filtered(lambda p: p.state in ('draft', 'sent'))
                
                if draft_pos:
                    _logger.info("Processing %d draft POs for paid order %s", len(draft_pos), so.name)
                    draft_pos.auto_confirm_and_notify_vendor()
                    processed += len(draft_pos)
        
        _logger.info("Processed %d draft purchase orders for paid sale orders", processed)
        return processed



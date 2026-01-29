# -*- coding: utf-8 -*-
from odoo import models
import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    def write(self, vals):
        """
        When a customer invoice becomes paid / in_payment,
        automatically trigger dropship PO creation and auto-confirm +
        email vendor.
        """
        # Prevent infinite recursion - if we're already processing dropship, skip
        if self.env.context.get('skip_dropship_processing'):
            return super().write(vals)
        
        # Track original payment states before write
        original_payment_states = {inv.id: inv.payment_state for inv in self}
        payment_state_in_vals = 'payment_state' in vals
        # Also check if matched_payment_ids changed (this triggers payment_state recomputation)
        matched_payment_ids_in_vals = 'matched_payment_ids' in vals

        # Execute native write
        res = super().write(vals)

        # Flush and invalidate to ensure computed fields are up to date
        # This is important when payment_state changes due to reconciliation (not in vals)
        self.env.flush_all()
        self.env.invalidate_all()

        # Check if payment_state actually changed (it might be computed, not directly written)
        # Also check if payment_state is in vals or if it changed after write
        payment_state_changed = False
        invoices_to_process = []
        
        # Only check for customer invoices
        customer_invoices = self.filtered(lambda inv: inv.move_type == 'out_invoice')
        
        if customer_invoices:
            _logger.info("ox_sale_dropship_postpaid: write() called for %d customer invoice(s), payment_state_in_vals=%s, matched_payment_ids_in_vals=%s", 
                        len(customer_invoices), payment_state_in_vals, matched_payment_ids_in_vals)
            for inv in customer_invoices:
                _logger.info("  Invoice %s: original_payment_state=%s", inv.name, original_payment_states.get(inv.id))
        
        if payment_state_in_vals:
            payment_state_changed = True
            # If payment_state is in vals, we know it changed
            for inv in customer_invoices:
                invoices_to_process.append((inv, inv.payment_state))
                _logger.debug("Invoice %s: payment_state in vals = %s", inv.name, inv.payment_state)
        elif matched_payment_ids_in_vals:
            # matched_payment_ids changed - reconciliation just happened
            # Check if invoice is now paid (regardless of whether payment_state changed in this write)
            # This handles the case where payment_state changed to paid in a previous write()
            _logger.debug("matched_payment_ids in vals - reconciliation happened, checking if invoice is paid")
            # The flush/invalidate above should have triggered recomputation
            # Now check if invoice is paid
            for inv in customer_invoices:
                old_state = original_payment_states.get(inv.id)
                new_state = inv.payment_state
                
                _logger.debug("Invoice %s: payment_state check after matched_payment_ids change - old=%s, new=%s", 
                            inv.name, old_state, new_state)
                
                # If invoice is now paid/in_payment, process it (even if it was already paid)
                # The _process_dropship_for_paid_invoice() method is idempotent and will skip if already processed
                if new_state in ('paid', 'in_payment'):
                    payment_state_changed = True
                    if old_state != new_state:
                        _logger.info("Invoice %s payment_state changed from %s to %s (matched_payment_ids changed)", 
                                    inv.name, old_state, new_state)
                    else:
                        _logger.info("Invoice %s is already %s, but matched_payment_ids changed - processing dropship", 
                                    inv.name, new_state)
                    invoices_to_process.append((inv, new_state))
        else:
            # Check if payment_state changed even if not in vals (computed field)
            # This can happen when reconciliation occurs (matched_payment_ids changes)
            for inv in customer_invoices:
                old_state = original_payment_states.get(inv.id)
                # After flush/invalidate, reading payment_state will get the recomputed value
                # This is safe because we're not calling _compute_payment_state() directly
                new_state = inv.payment_state
                
                _logger.debug("Invoice %s: payment_state check - old=%s, new=%s", inv.name, old_state, new_state)
                
                if old_state != new_state:
                    payment_state_changed = True
                    _logger.info("Invoice %s payment_state changed from %s to %s (not in vals, likely due to reconciliation)", 
                                inv.name, old_state, new_state)
                    invoices_to_process.append((inv, new_state))

        # If payment_state not updated → nothing for us to do
        if not payment_state_changed:
            return res

        # Dropship route detection
        dropship_route = self.env['stock.route'].search([('name', 'ilike', 'dropship')], limit=1)
        if not dropship_route:
            _logger.debug("No dropship route found, skipping auto-confirmation")
            return res

        # Process invoices that changed to paid/in_payment
        for inv, payment_state in invoices_to_process:
            # Only when invoice is actually paid / in payment
            if payment_state not in ('paid', 'in_payment'):
                _logger.debug("Invoice %s payment_state is %s (not paid/in_payment), skipping", inv.name, payment_state)
                continue

            _logger.info("Processing paid invoice %s (payment_state: %s)", inv.name, payment_state)
            
            # Process dropship for this invoice with context flag to prevent recursion
            try:
                inv.with_context(skip_dropship_processing=True)._process_dropship_for_paid_invoice()
            except Exception as e:
                _logger.error("Error processing dropship for invoice %s: %s", inv.name, str(e), exc_info=True)

        return res
    
    def _process_dropship_for_paid_invoice(self):
        """
        Process dropship POs for a paid invoice.
        Can be called from write() or from account.payment action_post()
        
        This method ONLY:
        1. Finds sale orders from invoice
        2. Launches procurement for dropship lines
        3. Finds purchase orders
        4. Calls auto_confirm_and_notify_vendor() on POs
        
        All email logic is handled by purchase.order.auto_confirm_and_notify_vendor()
        which is idempotent and ensures only one email per PO.
        
        Note: This method should be called on a single invoice recordset.
        """
        # Ensure we're working with a single invoice
        if len(self) != 1:
            _logger.error("_process_dropship_for_paid_invoice() should be called on a single invoice, got %d", len(self))
            return
        
        inv = self
        
        # Dropship route detection
        dropship_route = self.env['stock.route'].search([('name', 'ilike', 'dropship')], limit=1)
        if not dropship_route:
            _logger.debug("No dropship route found, skipping auto-confirmation")
            return
        
        # Get related sale orders via invoice lines -> sale_line_ids -> order_id
        sale_orders = inv.invoice_line_ids.sale_line_ids.mapped('order_id')

        if not sale_orders:
            _logger.debug("No sale orders found for invoice %s", inv.name)
            return

        _logger.info("Processing %d sale orders for invoice %s", len(sale_orders), inv.name)

        # Collect all dropship lines from all sale orders
        all_dropship_lines = self.env['sale.order.line']
        for so in sale_orders:
            dropship_lines = so.order_line.filtered(
                lambda l: (
                    (l.route_id and l.route_id.id == dropship_route.id)
                    or (dropship_route in l.product_id.route_ids)
                    or (l.product_id.categ_id and dropship_route in l.product_id.categ_id.route_ids)
                )
            )
            if dropship_lines:
                all_dropship_lines |= dropship_lines
                _logger.info("Found %d dropship lines in order %s", len(dropship_lines), so.name)

        if not all_dropship_lines:
            _logger.debug("No dropship lines found for invoice %s", inv.name)
            return

        # Launch procurement for all dropship lines
        try:
            all_dropship_lines.with_context(
                force_allow_dropship_procurement=True  # Bypass payment check
            )._action_launch_stock_rule()
            _logger.info("Launched stock rule for %d dropship lines", len(all_dropship_lines))
        except Exception as e:
            _logger.error("Error launching stock rule: %s", str(e), exc_info=True)
            return

        # Flush to ensure POs are created
        self.env.flush_all()
        self.env.invalidate_all()

        # Find all purchase orders (retry mechanism: procurement might create POs asynchronously)
        purchase_orders = self.env['purchase.order']
        max_retries = 5
        for retry in range(max_retries):
            if retry > 0:
                self.env.invalidate_all()
                _logger.debug("Retry %d: Searching for purchase orders", retry)
            
            po_lines = self.env['purchase.order.line'].search([
                ('sale_line_id', 'in', all_dropship_lines.ids)
            ])
            purchase_orders = po_lines.mapped('order_id')
            
            if purchase_orders:
                _logger.info("Found %d purchase orders on retry %d", len(purchase_orders), retry)
                break

        if not purchase_orders:
            _logger.warning("No purchase orders found after %d retries for invoice %s", max_retries, inv.name)
            return

        # Copy carrier from sale order to purchase order
        try:
            purchase_orders._copy_carrier_from_sale_order()
            _logger.info("Copied carrier from sale orders to %d purchase orders", len(purchase_orders))
        except Exception as e:
            _logger.error("Error copying carrier to purchase orders: %s", str(e), exc_info=True)

        # Filter out POs that are already processed (optimization to avoid unnecessary calls)
        # Refresh records to get latest flag values
        purchase_orders.invalidate_recordset(['dropship_auto_email_processed'])
        unprocessed_pos = purchase_orders.filtered(lambda p: not p.dropship_auto_email_processed)
        
        if not unprocessed_pos:
            _logger.info("All %d POs for invoice %s already processed (dropship_auto_email_processed=True), skipping", 
                       len(purchase_orders), inv.name)
            return
        
        # Call auto_confirm_and_notify_vendor() on unprocessed POs only
        # The PO method itself is idempotent and will handle:
        # - Confirming draft/sent POs
        # - Sending email only once (using dropship_auto_email_processed flag)
        # - Skipping already processed POs
        _logger.info("Calling auto_confirm_and_notify_vendor() for %d unprocessed POs (idempotent - safe to call multiple times)", len(unprocessed_pos))
        try:
            unprocessed_pos.auto_confirm_and_notify_vendor()
            _logger.info("Successfully processed %d purchase orders for invoice %s", len(unprocessed_pos), inv.name)
        except Exception as e:
            _logger.error("Error processing purchase orders for invoice %s: %s", inv.name, str(e), exc_info=True)
    
    def action_process_dropship_manually(self):
        """
        Manual action to process dropship POs for this invoice.
        Can be called from a button or as a fallback method.
        """
        for inv in self:
            if inv.move_type != 'out_invoice':
                continue
            if inv.payment_state not in ('paid', 'in_payment'):
                _logger.warning("Invoice %s is not paid (payment_state: %s), cannot process dropship", 
                              inv.name, inv.payment_state)
                continue
            try:
                inv._process_dropship_for_paid_invoice()
            except Exception as e:
                _logger.error("Error manually processing dropship for invoice %s: %s", inv.name, str(e), exc_info=True)

# -*- coding: utf-8 -*-
from odoo import models, api, fields
import logging

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def write(self, vals):
        """
        Hook into write to catch when state changes to 'done'.
        This ensures we catch payments even if _set_done isn't called.
        """
        state_changed_to_done = False
        if 'state' in vals and vals['state'] == 'done':
            # Check if state is actually changing to done
            for tx in self:
                if tx.state != 'done':
                    state_changed_to_done = True
                    break
        
        res = super().write(vals)
        
        # If state changed to done, process dropship POs
        # Check both sale_order_ids and invoice_ids/invoice_id
        if state_changed_to_done:
            self.env.flush_all()
            # Filter transactions that have either sale orders or invoices
            txs_to_process = self.filtered(
                lambda t: t.state == 'done' and (
                    t.sale_order_ids or 
                    (hasattr(t, 'invoice_ids') and t.invoice_ids) or
                    (hasattr(t, 'invoice_id') and t.invoice_id)
                )
            )
            for tx in txs_to_process:
                try:
                    _logger.info("State changed to 'done' for transaction %s, processing dropship POs", tx.reference)
                    self._process_dropship_for_transaction(tx)
                except Exception as e:
                    _logger.error("Error in write method for transaction %s: %s", tx.reference, str(e), exc_info=True)
        
        return res

    def _create_and_reconcile_invoice_from_sale_order(self):
        """
        Create invoice from sale order when payment is received via sale order link.
        
        Flow:
        1. Create invoice from sale order
        2. Link invoice to transaction (so account_payment module can find it)
        3. Post invoice
        4. account_payment module automatically creates payment with invoice_ids and reconciles
           (see: account_payment/models/payment_transaction.py _post_process() and _create_payment())
        """
        self.ensure_one()
        
        if not self.sale_order_ids:
            _logger.debug("Transaction %s has no sale orders, skipping invoice creation", self.reference)
            return
        
        # Get confirmed sale orders
        confirmed_orders = self.sale_order_ids.filtered(lambda so: so.state == 'sale')
        if not confirmed_orders:
            _logger.debug("Transaction %s has no confirmed sale orders, skipping invoice creation", self.reference)
            return
        
        # Check if invoice already exists
        if hasattr(self, 'invoice_ids') and self.invoice_ids:
            _logger.debug("Transaction %s already has invoices, skipping creation", self.reference)
            return
        
        _logger.info("Creating invoice from sale order(s) for transaction %s", self.reference)
        
        try:
            # Create invoices from sale orders (same logic as sale module's _invoice_sale_orders)
            fully_paid_orders = confirmed_orders.filtered(lambda so: so._is_paid())
            
            # Create a down payment invoice for partially paid orders
            downpayment_invoices = (
                confirmed_orders - fully_paid_orders
            )._generate_downpayment_invoices()
            
            # For fully paid orders create a final invoice
            fully_paid_orders._force_lines_to_invoice_policy_order()
            final_invoices = fully_paid_orders.with_context(
                raise_if_nothing_to_invoice=False
            )._create_invoices(final=True)
            
            invoices = downpayment_invoices + final_invoices
            
            if not invoices:
                _logger.debug("No invoices created for transaction %s", self.reference)
                return
            
            # Setup access token in advance
            for invoice in invoices:
                invoice._portal_ensure_token()
            
            # Link invoices to transaction (REQUIRED)
            # account_payment module's _create_payment() uses self.invoice_ids to link invoices to payment
            # Without this, the payment won't know which invoices to reconcile with
            if hasattr(self, 'invoice_ids'):
                self.invoice_ids = [(6, 0, invoices.ids)]
            
            # Post invoices
            # account_payment module will automatically create payment and reconcile in _post_process()
            invoices.action_post()
            _logger.info("Created and posted %d invoice(s) for transaction %s: %s. Payment will be auto-created and reconciled by account_payment module.", 
                        len(invoices), self.reference, ', '.join(invoices.mapped('name')))
            
        except Exception as e:
            _logger.error("Error creating invoice for transaction %s: %s", self.reference, str(e), exc_info=True)
            raise
    
    def _process_dropship_for_transaction(self, tx):
        """
        Helper method to process dropship POs for a transaction.
        Called from both _set_done and write methods.
        Handles both SO payments and invoice payments.
        
        This method ONLY:
        1. Finds sale orders (from SO or invoices)
        2. Launches procurement for dropship lines
        3. Finds purchase orders
        4. Calls auto_confirm_and_notify_vendor() on POs
        
        All email logic is handled by purchase.order.auto_confirm_and_notify_vendor()
        which is idempotent and ensures only one email per PO.
        """
        dropship_route = self.env['stock.route'].search([('name', 'ilike', 'dropship')], limit=1)
        if not dropship_route:
            return
        
        # Get sale orders from transaction (either directly or via invoices)
        sale_orders = tx.sale_order_ids
        
        # Also check if transaction is linked to invoices (invoice payment link)
        if hasattr(tx, 'invoice_ids') and tx.invoice_ids:
            # Get sale orders from invoices
            invoice_sale_orders = tx.invoice_ids.mapped('invoice_line_ids.sale_line_ids.order_id')
            sale_orders |= invoice_sale_orders
        elif hasattr(tx, 'invoice_id') and tx.invoice_id:
            # Some payment providers use invoice_id (singular)
            invoice_sale_orders = tx.invoice_id.invoice_line_ids.sale_line_ids.mapped('order_id')
            sale_orders |= invoice_sale_orders
        
        if not sale_orders:
            _logger.debug("Transaction %s has no sale orders (directly or via invoices)", tx.reference)
            return
        
        _logger.info("Processing dropship for transaction %s with %d sale orders", tx.reference, len(sale_orders))
        
        # Launch procurement for dropship lines (creates POs if needed)
        for order in sale_orders:
            dropship_lines = order.order_line.filtered(
                lambda l: (
                    (l.route_id and l.route_id.id == dropship_route.id)
                    or (dropship_route in l.product_id.route_ids)
                    or (l.product_id.categ_id and dropship_route in l.product_id.categ_id.route_ids)
                )
            )
            if dropship_lines:
                try:
                    dropship_lines.with_context(
                        skip_procurement=False,
                        force_allow_dropship_procurement=True
                    )._action_launch_stock_rule()
                    _logger.info("Launched stock rule for dropship lines in order %s", order.name)
                except Exception as e:
                    _logger.error("Error launching stock rule: %s", str(e), exc_info=True)
        
        # Flush to ensure POs are created
        self.env.flush_all()
        self.env.invalidate_all()
        
        # Find all purchase orders for these dropship lines
        all_dropship_lines = sale_orders.mapped('order_line').filtered(
            lambda l: (
                (l.route_id and l.route_id.id == dropship_route.id)
                or (dropship_route in l.product_id.route_ids)
                or (l.product_id.categ_id and dropship_route in l.product_id.categ_id.route_ids)
            )
        )
        
        if not all_dropship_lines:
            return
        
        # Retry mechanism: procurement might create POs asynchronously
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
            _logger.warning("No purchase orders found after %d retries for transaction %s", max_retries, tx.reference)
            return
        
        # Filter out POs that are already processed (optimization to avoid unnecessary calls)
        # Refresh records to get latest flag values
        purchase_orders.invalidate_recordset(['dropship_auto_email_processed'])
        unprocessed_pos = purchase_orders.filtered(lambda p: not p.dropship_auto_email_processed)
        
        if not unprocessed_pos:
            _logger.info("All %d POs for transaction %s already processed (dropship_auto_email_processed=True), skipping", 
                       len(purchase_orders), tx.reference)
            return
        
        # Call auto_confirm_and_notify_vendor() on unprocessed POs only
        # The PO method itself is idempotent and will handle:
        # - Confirming draft/sent POs
        # - Sending email only once (using dropship_auto_email_processed flag)
        # - Skipping already processed POs
        _logger.info("Calling auto_confirm_and_notify_vendor() for %d unprocessed POs (idempotent - safe to call multiple times)", len(unprocessed_pos))
        try:
            unprocessed_pos.auto_confirm_and_notify_vendor()
            _logger.info("Successfully processed %d purchase orders for transaction %s", len(unprocessed_pos), tx.reference)
        except Exception as e:
            _logger.error("Error processing purchase orders for transaction %s: %s", tx.reference, str(e), exc_info=True)

    def _set_done(self, state_message=None, extra_allowed_states=()):
        """
        When an online payment is completed (payment link paid),
        automatically:
        1. Create invoice from sale order (if not already created)
        2. Create payment record and reconcile with invoice
        3. Trigger dropship PO creation AND auto-confirm + email vendor
        """
        # Call native behavior first
        txs = super()._set_done(state_message=state_message, extra_allowed_states=extra_allowed_states)

        # Ensure transaction state is flushed before proceeding
        self.env.flush_all()

        for tx in txs:
            _logger.info("Processing payment transaction %s (state: %s) in _set_done", tx.reference, tx.state)
            
            # Step 1: Create invoice from sale order if payment is via sale order link
            if tx.sale_order_ids and not tx.invoice_ids:
                try:
                    tx._create_and_reconcile_invoice_from_sale_order()
                except Exception as e:
                    _logger.error("Error creating/reconciling invoice for transaction %s: %s", tx.reference, str(e), exc_info=True)
            
            # Step 2: Process dropship POs using helper method
            # The helper method handles: finding sale orders, launching procurement, finding POs, and calling auto_confirm_and_notify_vendor()
            try:
                self._process_dropship_for_transaction(tx)
            except Exception as e:
                _logger.error("Error in _set_done processing transaction %s: %s", tx.reference, str(e), exc_info=True)

        return txs

    def _post_process(self):
        """
        Additional hook after payment processing.
        This ensures we catch payments even if _set_done doesn't trigger our code.
        """
        # Use savepoint to isolate errors from super()._post_process()
        # This prevents transaction failure from affecting our dropship processing
        savepoint_name = 'ox_sale_dropship_postpaid_post_process'
        try:
            self.env.cr.execute('SAVEPOINT %s' % savepoint_name)
            res = super()._post_process()
            self.env.cr.execute('RELEASE SAVEPOINT %s' % savepoint_name)
        except Exception as e:
            # Rollback to savepoint to recover from the error
            self.env.cr.execute('ROLLBACK TO SAVEPOINT %s' % savepoint_name)
            # Handle non-critical errors like duplicate mail followers
            # (partner already subscribed to sale order)
            if 'mail_followers' in str(e) and 'duplicate key' in str(e).lower():
                _logger.warning("Non-critical mail follower subscription error (partner already subscribed): %s", str(e))
                # Continue processing - this is not a critical error
                res = True
            else:
                # Re-raise other errors
                raise
        
        # Only process if transaction is done and has sale orders or invoices
        for tx in self.filtered(
            lambda t: t.state == 'done' and (
                t.sale_order_ids or 
                (hasattr(t, 'invoice_ids') and t.invoice_ids) or
                (hasattr(t, 'invoice_id') and t.invoice_id)
            )
        ):
            try:
                # Use the same processing logic as _set_done
                # But only if POs haven't been processed yet (check by looking for draft POs)
                dropship_route = self.env['stock.route'].search([('name', 'ilike', 'dropship')], limit=1)
                if not dropship_route:
                    continue
                
                # Use the helper method which now handles both SO and invoice payments
                try:
                    self._process_dropship_for_transaction(tx)
                except Exception as e:
                    _logger.error("Error in _post_process processing transaction %s: %s", tx.reference, str(e), exc_info=True)
            except Exception as e:
                _logger.error("Error in _post_process for transaction %s: %s", tx.reference, str(e), exc_info=True)
        
        return res

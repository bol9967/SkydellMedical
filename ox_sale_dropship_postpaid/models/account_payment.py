# -*- coding: utf-8 -*-
from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def action_post(self):
        """
        When a payment is posted, check if related invoices become paid
        and trigger dropship PO processing.
        """
        res = super().action_post()
        
        # After payment is posted, check related invoices
        # This handles manual payment registration
        _logger.info("="*80)
        _logger.info("ox_sale_dropship_postpaid: action_post() called for %d payment(s)", len(self))
        _logger.info("="*80)
        
        for payment in self:
            if payment.payment_type != 'inbound':
                continue
            
            # Flush to ensure payment move is created
            self.env.flush_all()
            
            # Get related invoices using multiple methods to catch all cases:
            # Priority order:
            # 1. invoice_ids: invoices explicitly linked to this payment (from payment wizard) - MOST RELIABLE
            # 2. reconciled_invoice_ids: invoices that are already reconciled
            # 3. From payment move lines: invoices linked via move lines (reconciliation)
            _logger.info("Payment %s: Checking for invoices...", payment.name)
            _logger.info("  - payment.invoice_ids: %d", len(payment.invoice_ids))
            _logger.info("  - payment.reconciled_invoice_ids: %d", len(payment.reconciled_invoice_ids))
            _logger.info("  - payment.move_id: %s", payment.move_id.name if payment.move_id else 'None')
            
            invoices = payment.invoice_ids | payment.reconciled_invoice_ids
            
            # If no invoices found via direct links, check payment move lines for reconciliation
            # This is critical for manual payments where reconciliation happens via move lines
            if not invoices and payment.move_id:
                _logger.info("  No invoices via direct links, checking move lines...")
                payment_move_lines = payment.move_id.line_ids
                _logger.info("  - Payment move has %d lines", len(payment_move_lines))
                
                # Check all matched lines (reconciliation records)
                for line in payment_move_lines:
                    # Get reconciled invoice lines from this payment line
                    matched_lines = line.matched_debit_ids.mapped('debit_move_id') | \
                                   line.matched_credit_ids.mapped('credit_move_id')
                    _logger.debug("  - Line %s: matched with %d lines", line.account_id.name, len(matched_lines))
                    for matched_line in matched_lines:
                        matched_move = matched_line.move_id
                        if matched_move.move_type == 'out_invoice':
                            invoices |= matched_move
                            _logger.info("  - Found customer invoice via move line: %s", matched_move.name)
            
            # Filter to customer invoices only
            invoices = invoices.filtered(lambda inv: inv.move_type == 'out_invoice')
            
            if not invoices:
                _logger.warning("Payment %s posted, but no customer invoices found. "
                            "reconciled_invoice_ids=%d, invoice_ids=%d, move_id=%s, partner=%s, amount=%s. "
                            "This might indicate invoices weren't linked during payment creation, "
                            "or reconciliation hasn't happened yet. The account_move write() method "
                            "should catch this when invoices are reconciled later.",
                            payment.name,
                            len(payment.reconciled_invoice_ids),
                            len(payment.invoice_ids),
                            payment.move_id.name if payment.move_id else 'None',
                            payment.partner_id.name if payment.partner_id else 'None',
                            payment.amount)
                
                # Fallback: Try to find invoices by partner and payment date
                # This helps catch cases where payment was created without linking invoices
                if payment.partner_id:
                    potential_invoices = self.env['account.move'].search([
                        ('move_type', '=', 'out_invoice'),
                        ('partner_id', '=', payment.partner_id.id),
                        ('state', '=', 'posted'),
                        ('payment_state', 'in', ('partial', 'not_paid')),
                        ('invoice_date_due', '<=', payment.date),
                    ], limit=10)
                    if potential_invoices:
                        _logger.info("Found %d potential invoices for partner %s. "
                                    "These might be the invoices this payment should reconcile with.",
                                    len(potential_invoices), payment.partner_id.name)
                continue
            
            _logger.info("Payment %s posted, found %d related customer invoices for dropship processing", 
                        payment.name, len(invoices))
            
            # Process each invoice - ensure payment_state is recomputed and check if paid
            for invoice in invoices:
                # Force recomputation of payment_state
                invoice.invalidate_recordset(['payment_state'])
                invoice._compute_payment_state()
                invoice.flush_recordset(['payment_state'])
                self.env.invalidate_all()
                
                _logger.debug("Invoice %s payment_state after recompute: %s", invoice.name, invoice.payment_state)
                
                # Trigger the write method logic by checking payment_state
                if invoice.payment_state in ('paid', 'in_payment'):
                    _logger.info("Invoice %s is now %s after payment %s, triggering dropship processing", 
                               invoice.name, invoice.payment_state, payment.name)
                    try:
                        # Call the processing logic directly
                        # The account_move write() method will also catch this when payment_state changes
                        # but we call it directly here to ensure it happens immediately
                        # Use context flag to prevent recursion if write() is triggered
                        invoice.with_context(skip_dropship_processing=True)._process_dropship_for_paid_invoice()
                    except Exception as e:
                        _logger.error("Error processing dropship for invoice %s after payment %s: %s",
                                    invoice.name, payment.name, str(e), exc_info=True)
                else:
                    _logger.warning("Invoice %s payment_state is %s (not paid/in_payment yet) after payment %s. "
                                "This might happen if reconciliation hasn't completed yet. "
                                "The invoice write() method should catch this when payment_state changes.", 
                                invoice.name, invoice.payment_state, payment.name)
                    # Try to trigger a write to force payment_state recomputation
                    # This helps catch cases where reconciliation happened but payment_state wasn't recomputed
                    try:
                        invoice.invalidate_recordset(['payment_state'])
                        # Force a write to trigger the write() method which will check payment_state
                        invoice.write({'invoice_date': invoice.invoice_date})  # No-op write to trigger write()
                    except Exception as e:
                        _logger.debug("Could not trigger write on invoice %s: %s", invoice.name, str(e))
        
        return res
    


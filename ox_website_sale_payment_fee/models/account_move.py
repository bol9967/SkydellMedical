# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import _, api, fields, models
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    payment_fee_added = fields.Boolean(
        string="Payment Fee Added",
        default=False,
        help="Indicates if the card processing fee has been added to this invoice"
    )

    def _get_payment_fee_provider(self):
        """Get the payment provider to use for fee calculation from related sale order or transaction."""
        self.ensure_one()
        # Try to get provider from related sale order
        sale_order = self._get_related_sale_order()
        if sale_order and sale_order.selected_payment_provider_id:
            return sale_order.selected_payment_provider_id
        
        # Try to get from transaction
        if self.transaction_ids:
            for tx in self.transaction_ids:
                if tx.provider_id and tx.provider_id.payment_fee_enabled:
                    return tx.provider_id
        
        return None

    def _get_related_sale_order(self):
        """Get the sale order related to this invoice."""
        self.ensure_one()
        # Check via invoice lines
        for line in self.invoice_line_ids:
            if line.sale_line_ids:
                return line.sale_line_ids[0].order_id
        
        # Check via invoice_origin
        if self.invoice_origin:
            sale_order = self.env['sale.order'].search([
                ('name', '=', self.invoice_origin)
            ], limit=1)
            if sale_order:
                return sale_order
        
        return None

    def _get_payment_fee_product(self, provider=None):
        """Get or create the payment processing fee product."""
        self.ensure_one()
        provider = provider or self._get_payment_fee_provider()
        
        # Use provider-specific product if set
        if provider and provider.payment_fee_product_id:
            return provider.payment_fee_product_id
        
        # Search for existing product by default_code
        product = self.env['product.product'].search([
            ('default_code', '=', 'PAYMENT_PROCESSING_FEE')
        ], limit=1)
        
        if not product:
            product = self.env['product.product'].create({
                'name': _('Card Processing Fee'),
                'default_code': 'PAYMENT_PROCESSING_FEE',
                'type': 'service',
                'sale_ok': True,
                'purchase_ok': False,
                'list_price': 0.0,
                'taxes_id': False,  # No taxes on processing fee
            })
        
        return product

    def _get_payment_fee_percentage(self, provider=None):
        """Get the payment processing fee percentage from provider."""
        self.ensure_one()
        provider = provider or self._get_payment_fee_provider()
        
        if provider and provider.payment_fee_enabled:
            return provider.payment_fee_percentage
        
        return 0.0

    def _calculate_payment_fee_amount(self, provider=None):
        """Calculate the payment processing fee amount for invoice.
        
        Fee is calculated as a percentage of: untaxed amount + delivery charges
        
        This applies to:
        - Invoices created from sale orders (with delivery charges from sale order)
        - Direct invoice payment links
        
        The base amount includes:
        - All invoice lines (untaxed amount via price_subtotal)
        - Delivery/shipping charges (identified via related sale order delivery lines)
        - Excludes: payment fee lines themselves
        """
        self.ensure_one()
        provider = provider or self._get_payment_fee_provider()
        
        _logger.info("=== _calculate_payment_fee_amount START for invoice %s ===", self.name)
        
        if not provider or not provider.payment_fee_enabled:
            _logger.info("Provider not found or fee not enabled - returning 0.0")
            return 0.0
        
        fee_percentage = self._get_payment_fee_percentage(provider)
        _logger.info("Fee percentage: %s", fee_percentage)
        
        # Calculate base amount: untaxed amount + delivery charges
        # Include all invoice lines except payment fee lines
        # price_subtotal gives us the untaxed amount per line
        fee_product = self._get_payment_fee_product(provider)
        base_lines = self.invoice_line_ids.filtered(
            lambda l: not l.display_type and l.product_id.id != fee_product.id
        )
        base_amount = sum(base_lines.mapped('price_subtotal'))
        
        # Identify delivery lines (from sale order delivery lines)
        delivery_lines = self.invoice_line_ids.filtered(
            lambda l: not l.display_type 
                     and l.product_id.id != fee_product.id
                     and l.sale_line_ids 
                     and any(line.is_delivery for line in l.sale_line_ids)
        )
        delivery_amount = sum(delivery_lines.mapped('price_subtotal'))
        non_delivery_amount = base_amount - delivery_amount
        
        _logger.info("Base calculation: non_delivery_lines=%s (amount=%s), delivery_lines=%s (amount=%s), total_base=%s", 
                    len(base_lines) - len(delivery_lines),
                    non_delivery_amount,
                    len(delivery_lines),
                    delivery_amount,
                    base_amount)
        
        if float_is_zero(base_amount, precision_rounding=self.currency_id.rounding):
            # Fallback to amount_untaxed (excluding existing fee)
            existing_fee_lines = self.invoice_line_ids.filtered(
                lambda l: l.product_id.id == fee_product.id
            )
            existing_fee_amount = sum(existing_fee_lines.mapped('price_subtotal'))
            base_amount = self.amount_untaxed - existing_fee_amount
            _logger.info("Base amount was 0, using fallback: amount_untaxed=%s, existing_fee_amount=%s, base_amount=%s",
                        self.amount_untaxed, existing_fee_amount, base_amount)
        
        # Calculate fee on: untaxed amount + delivery charges
        fee_amount = base_amount * (fee_percentage / 100.0)
        _logger.info("Fee calculation: base_amount=%s (untaxed + delivery) * (fee_percentage=%s / 100) = %s",
                    base_amount, fee_percentage, fee_amount)
        
        # Round to currency precision
        if self.currency_id:
            fee_amount = self.currency_id.round(fee_amount)
            _logger.info("Fee amount after rounding: %s", fee_amount)
        
        _logger.info("=== _calculate_payment_fee_amount END ===")
        return fee_amount

    def _add_payment_fee_line(self, provider=None):
        """Add or update the payment processing fee line on the invoice.
        
        Professional approach for posted invoices:
        - Check if fee already added (prevent duplicates)
        - Check if invoice is paid/reconciled (guard condition)
        - If posted: revert to draft, add fee, re-post immediately
        - If draft: add fee normally
        
        Returns True if fee was added, False otherwise.
        """
        self.ensure_one()
        
        _logger.info("=== _add_payment_fee_line START for invoice %s ===", self.name)
        _logger.info("Invoice state=%s, move_type=%s, amount_total=%s, payment_fee_added=%s", 
                    self.state, self.move_type, self.amount_total, self.payment_fee_added)
        
        provider = provider or self._get_payment_fee_provider()
        
        if provider:
            _logger.info("Provider: ID=%s, name=%s, fee_enabled=%s, fee_percentage=%s", 
                       provider.id, provider.name, provider.payment_fee_enabled, provider.payment_fee_percentage)
        else:
            _logger.warning("No provider found")
        
        if not provider or not provider.payment_fee_enabled:
            _logger.info("Provider not found or fee not enabled - removing fee line and returning False")
            self._remove_payment_fee_line()
            return False
        
        # Guard: Check if fee already added (prevent duplicates)
        if self.payment_fee_added:
            _logger.info("Payment fee already added to this invoice - skipping to prevent duplicate")
            # Verify fee line still exists
            fee_product = self._get_payment_fee_product(provider)
            existing_fee_line = self.invoice_line_ids.filtered(
                lambda l: l.product_id.id == fee_product.id
            )
            if existing_fee_line:
                _logger.info("Fee line exists - returning True")
                return True
            else:
                _logger.warning("payment_fee_added flag is True but fee line not found - resetting flag")
                self.payment_fee_added = False
        
        # Guard: Check if invoice is paid or reconciled (don't modify if paid)
        if self.state == 'posted':
            # Check payment state
            payment_state = getattr(self, 'payment_state', False)
            if payment_state in ('paid', 'in_payment'):
                _logger.warning("Invoice is paid (payment_state=%s) - cannot add fee", payment_state)
                return False
            
            # Check if invoice lines are reconciled
            reconciled_lines = self.line_ids.filtered(lambda l: l.reconciled)
            if reconciled_lines:
                _logger.warning("Invoice has reconciled lines - cannot add fee")
                return False
        
        fee_product = self._get_payment_fee_product(provider)
        _logger.info("Fee product: ID=%s, name=%s, default_code=%s", 
                    fee_product.id, fee_product.name, fee_product.default_code)
        
        fee_amount = self._calculate_payment_fee_amount(provider)
        _logger.info("Fee amount calculated: %s", fee_amount)
        
        # Skip if fee amount is zero
        if float_is_zero(fee_amount, precision_rounding=self.currency_id.rounding):
            _logger.info("Fee amount is zero - removing fee line and returning False")
            self._remove_payment_fee_line()
            return False
        
        fee_percentage = self._get_payment_fee_percentage(provider)
        provider_name = provider.name if provider else _('Payment')
        
        # Professional approach: For posted invoices, revert to draft, add fee, re-post
        was_posted = self.state == 'posted'
        original_state = self.state
        
        try:
            if was_posted:
                _logger.info("Invoice is posted - reverting to draft to add fee line")
                # Revert to draft (using sudo for permissions)
                self.sudo().button_draft()
                _logger.info("Invoice reverted to draft")
            
            # Find existing fee line
            fee_line = self.invoice_line_ids.filtered(
                lambda l: l.product_id.id == fee_product.id
            )
            _logger.info("Existing fee line found: %s", bool(fee_line))
            
            # Get product UOM
            product_uom = fee_product.uom_id
            
            if fee_line:
                _logger.info("Updating existing fee line: ID=%s", fee_line.id)
                fee_line.write({
                    'product_id': fee_product.id,
                    'product_uom_id': product_uom.id,
                    'quantity': 1.0,
                    'price_unit': fee_amount,
                    'name': _('Card Processing Fee (%s%%) - %s') % (fee_percentage, provider_name),
                    'tax_ids': [(5, 0, 0)],  # Remove all taxes
                })
                _logger.info("Fee line updated successfully")
            else:
                _logger.info("Creating new fee line")
                fee_line = self.env['account.move.line'].create({
                    'move_id': self.id,
                    'product_id': fee_product.id,
                    'product_uom_id': product_uom.id,
                    'quantity': 1.0,
                    'price_unit': fee_amount,
                    'name': _('Card Processing Fee (%s%%) - %s') % (fee_percentage, provider_name),
                    'tax_ids': [(5, 0, 0)],  # No taxes
                })
                _logger.info("Fee line created successfully: ID=%s", fee_line.id)
            
            # Recompute amounts
            self.invalidate_recordset(['amount_total', 'amount_untaxed', 'amount_tax', 'amount_residual'])
            self._compute_amount()
            
            # Mark fee as added
            self.payment_fee_added = True
            
            # Re-post invoice if it was posted before
            if was_posted:
                _logger.info("Re-posting invoice after adding fee line")
                self.sudo().action_post()
                _logger.info("Invoice re-posted successfully")
            
            _logger.info("Payment fee line added to invoice %s (original_state=%s, current_state=%s): amount=%s, invoice_total=%s", 
                        self.name, original_state, self.state, fee_amount, self.amount_total)
            _logger.info("=== _add_payment_fee_line END ===")
            return True
        except Exception as e:
            _logger.error("Error adding payment fee line to invoice: %s", str(e), exc_info=True)
            # Try to restore original state if we reverted to draft
            if was_posted and self.state == 'draft':
                try:
                    _logger.warning("Attempting to restore invoice to posted state after error")
                    self.sudo().action_post()
                except Exception as restore_error:
                    _logger.error("Failed to restore invoice state: %s", str(restore_error))
            return False

    def _remove_payment_fee_line(self):
        """Remove the payment processing fee line from the invoice."""
        self.ensure_one()
        fee_product = self._get_payment_fee_product(None)
        if fee_product:
            fee_lines = self.invoice_line_ids.filtered(
                lambda l: l.product_id.id == fee_product.id
            )
            if fee_lines:
                fee_lines.unlink()
                self.invalidate_recordset(['amount_total', 'amount_untaxed', 'amount_tax', 'amount_residual'])
                self._compute_amount()
                # Reset the flag
                self.payment_fee_added = False


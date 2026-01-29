# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    has_payment_fee = fields.Boolean(
        string="Has Payment Processing Fee",
        compute='_compute_has_payment_fee',
        help="Indicates if this order has a payment processing fee line"
    )
    
    selected_payment_provider_id = fields.Many2one(
        string="Selected Payment Provider",
        comodel_name='payment.provider',
        help="Payment provider selected on checkout page"
    )

    @api.depends('order_line')
    def _compute_has_payment_fee(self):
        """Check if order has a payment processing fee line."""
        for order in self:
            order.has_payment_fee = bool(order.order_line.filtered(
                lambda line: line.is_payment_fee
            ))

    def _get_payment_fee_provider(self):
        """Get the payment provider to use for fee calculation."""
        self.ensure_one()
        # Use selected provider if available, otherwise check from session
        provider = self.selected_payment_provider_id
        if not provider and hasattr(self.env, 'context') and self.env.context.get('payment_provider_id'):
            provider = self.env['payment.provider'].browse(self.env.context['payment_provider_id'])
        return provider

    def _get_payment_fee_product(self, provider=None):
        """Get or create the payment processing fee product."""
        self.ensure_one()
        provider = provider or self._get_payment_fee_provider()
        
        # Use provider-specific product if set
        if provider and provider.payment_fee_product_id:
            return provider.payment_fee_product_id
        
        # Create default fee product if not exists
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
        """Get the payment processing fee percentage from provider or settings."""
        self.ensure_one()
        provider = provider or self._get_payment_fee_provider()
        
        # Use provider-specific percentage if enabled
        if provider and provider.payment_fee_enabled:
            return provider.payment_fee_percentage
        
        # Default to 4.0 if no provider or provider doesn't have fee enabled
        return 4.0

    def _calculate_payment_fee_amount(self, provider=None):
        """Calculate the payment processing fee amount.
        
        Fee is calculated as a percentage of: untaxed amount + delivery charges
        
        This applies to:
        - Website orders (orders with website_id)
        - Sale order payment links (portal payments, sale app links)
        
        The base amount includes:
        - All product lines (untaxed amount via price_subtotal)
        - Delivery/shipping charges (delivery lines)
        - Excludes: payment fee lines themselves
        """
        self.ensure_one()
        provider = provider or self._get_payment_fee_provider()
        
        _logger.info("=== _calculate_payment_fee_amount START for sale order %s ===", self.name)
        _logger.info("Order type: website_id=%s, is_website_order=%s", 
                    self.website_id, bool(self.website_id))
        
        # Check if fee should be applied for this provider
        if provider and not provider.payment_fee_enabled:
            _logger.info("Provider fee not enabled - returning 0.0")
            return 0.0
        
        fee_percentage = self._get_payment_fee_percentage(provider)
        _logger.info("Fee percentage: %s", fee_percentage)
        
        # Ensure order amounts are computed
        self._compute_amounts()
        
        # Calculate base amount: untaxed amount + delivery charges
        # Include all lines except payment fee lines
        # price_subtotal gives us the untaxed amount per line
        base_lines = self.order_line.filtered(lambda line: not line.is_payment_fee)
        base_amount = sum(base_lines.mapped('price_subtotal'))
        
        # Separate delivery lines for logging
        delivery_lines = self.order_line.filtered(lambda line: line.is_delivery and not line.is_payment_fee)
        delivery_amount = sum(delivery_lines.mapped('price_subtotal'))
        non_delivery_amount = sum(
            self.order_line.filtered(lambda line: not line.is_delivery and not line.is_payment_fee).mapped('price_subtotal')
        )
        
        _logger.info("Base calculation: non_delivery_lines=%s (amount=%s), delivery_lines=%s (amount=%s), total_base=%s", 
                    len(self.order_line.filtered(lambda line: not line.is_delivery and not line.is_payment_fee)),
                    non_delivery_amount,
                    len(delivery_lines),
                    delivery_amount,
                    base_amount)
        
        # If base_amount is 0, use amount_untaxed as fallback (excluding existing fee)
        if float_is_zero(base_amount, precision_rounding=self.currency_id.rounding):
            existing_fee_amount = sum(
                self.order_line.filtered(lambda line: line.is_payment_fee).mapped('price_subtotal')
            )
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
        """Add or update the payment processing fee line on the order.
        
        Works for both website orders and portal payments.
        Bypasses write protection for orders in 'done' state (for payment links).
        """
        self.ensure_one()
        
        _logger.info("=== _add_payment_fee_line START for sale order %s ===", self.name)
        _logger.info("Order state=%s, website_id=%s", self.state, self.website_id)
        
        provider = provider or self._get_payment_fee_provider()
        
        if provider:
            _logger.info("Provider: ID=%s, name=%s", provider.id, provider.name)
        else:
            _logger.warning("No provider found")
        
        # Check if fee should be applied (handles both website and portal payments)
        should_apply = self._should_apply_payment_fee(provider)
        _logger.info("Should apply payment fee: %s", should_apply)
        
        if not should_apply:
            _logger.info("Fee should not be applied - removing any existing fee line")
            self._remove_payment_fee_line()
            return
        
        fee_product = self._get_payment_fee_product(provider)
        _logger.info("Fee product: ID=%s, name=%s, default_code=%s", 
                    fee_product.id, fee_product.name, fee_product.default_code)
        
        fee_amount = self._calculate_payment_fee_amount(provider)
        
        _logger.info("Payment fee calculation: base_amount=%s, fee_percentage=%s, fee_amount=%s", 
                    self.amount_untaxed, self._get_payment_fee_percentage(provider), fee_amount)
        
        # Skip if fee amount is zero
        if float_is_zero(fee_amount, precision_rounding=self.currency_id.rounding):
            _logger.info("Fee amount is zero - removing any existing fee line")
            self._remove_payment_fee_line()
            return
        
        fee_percentage = self._get_payment_fee_percentage(provider)
        provider_name = provider.name if provider else _('Payment')
        
        # Use sudo() to bypass write protection when order is in 'done' or 'sale' state
        # This allows adding fee lines to confirmed/locked orders for payment links
        order_sudo = self.sudo() if self.state in ('done', 'sale') else self
        line_env = order_sudo.env['sale.order.line']
        
        _logger.info("Using sudo=%s (state=%s)", self.state in ('done', 'sale'), self.state)
        
        # Find existing fee line
        fee_line = order_sudo.order_line.filtered(lambda line: line.is_payment_fee)
        _logger.info("Existing fee line found: %s", bool(fee_line))
        
        # Get product UOM
        product_uom = fee_product.uom_id
        
        try:
            if fee_line:
                _logger.info("Updating existing fee line: ID=%s", fee_line.id)
                # Update existing fee line (use sudo if order is done or sale)
                fee_line_sudo = fee_line.sudo() if self.state in ('done', 'sale') else fee_line
                fee_line_sudo.write({
                    'product_id': fee_product.id,
                    'product_uom': product_uom.id,
                    'product_uom_qty': 1.0,
                    'price_unit': fee_amount,
                    'technical_price_unit': fee_amount,  # Set technical_price_unit to prevent recomputation
                    'name': _('Card Processing Fee (%s%%) - %s') % (fee_percentage, provider_name),
                    'tax_id': [(5, 0, 0)],  # Remove all taxes
                })
                _logger.info("Fee line updated successfully")
            else:
                _logger.info("Creating new fee line")
                # Create new fee line (use sudo if order is done)
                fee_line = line_env.create({
                    'order_id': order_sudo.id,
                    'product_id': fee_product.id,
                    'product_uom': product_uom.id,
                    'product_uom_qty': 1.0,
                    'price_unit': fee_amount,
                    'technical_price_unit': fee_amount,  # Set technical_price_unit to prevent recomputation
                    'is_payment_fee': True,
                    'name': _('Card Processing Fee (%s%%) - %s') % (fee_percentage, provider_name),
                    'tax_id': [(5, 0, 0)],  # No taxes
                })
                _logger.info("Fee line created successfully: ID=%s", fee_line.id)
            
            # Force recompute amounts (but not prices, as fee lines are excluded)
            order_sudo._compute_amounts()
            
            _logger.info("Payment fee line created/updated: price_unit=%s, technical_price_unit=%s, price_subtotal=%s, price_total=%s",
                        fee_line.price_unit, fee_line.technical_price_unit, fee_line.price_subtotal, fee_line.price_total)
            _logger.info("Order amount_total after fee: %s", order_sudo.amount_total)
        except Exception as e:
            _logger.error("Error adding payment fee line: %s", str(e), exc_info=True)
            raise
        
        _logger.info("=== _add_payment_fee_line END ===")

    def _remove_payment_fee_line(self):
        """Remove the payment processing fee line from the order."""
        self.ensure_one()
        fee_lines = self.order_line.filtered(lambda line: line.is_payment_fee)
        if fee_lines:
            fee_lines.unlink()
            self._recompute_prices()

    def _should_apply_payment_fee(self, provider=None):
        """Determine if payment fee should be applied.
        
        Fee is applied for website orders or portal payments with online payments when provider has fee enabled.
        Allows fee for orders in 'sale' (confirmed) or 'done' state (for payment links).
        """
        self.ensure_one()
        
        _logger.info("=== _should_apply_payment_fee START for sale order %s ===", self.name)
        _logger.info("Order state=%s, website_id=%s, transaction_ids=%s", 
                    self.state, self.website_id, self.transaction_ids)
        
        # Allow fee for website orders OR portal payments (orders without website_id but with transactions)
        # Portal payments typically don't have website_id but are still online payments
        is_website_order = bool(self.website_id)
        is_portal_payment = not self.website_id and self.transaction_ids
        
        _logger.info("is_website_order=%s, is_portal_payment=%s", is_website_order, is_portal_payment)
        
        if not is_website_order and not is_portal_payment:
            # For portal payments, we'll allow it if there's a provider with fee enabled
            # This will be checked below
            _logger.info("Not a website order or portal payment (yet)")
        
        provider = provider or self._get_payment_fee_provider()
        
        if provider:
            _logger.info("Provider: ID=%s, name=%s, fee_enabled=%s, fee_percentage=%s", 
                       provider.id, provider.name, provider.payment_fee_enabled, provider.payment_fee_percentage)
        else:
            _logger.warning("No provider found")
        
        # If provider is specified, check if it has fee enabled
        if provider:
            if not provider.payment_fee_enabled:
                _logger.info("Provider fee not enabled - returning False")
                return False
        else:
            # No provider selected, don't apply fee
            _logger.info("No provider selected - returning False")
            return False
        
        # Fee should be applied when order is in draft, sent, sale, or done state and has items
        # 'sale' state is confirmed order (for payment links)
        # 'done' state is allowed for payment links (bypassing normal write protection)
        # Portal payments might be in 'sent', 'sale', or 'done' state
        valid_states = ('draft', 'sent', 'sale', 'done')
        has_items = bool(self.order_line.filtered(
            lambda line: not line.is_delivery and not line.is_payment_fee
        ))
        
        _logger.info("State check: state=%s, valid_states=%s, state_valid=%s", 
                    self.state, valid_states, self.state in valid_states)
        _logger.info("Items check: has_items=%s", has_items)
        
        if self.state not in valid_states or not has_items:
            _logger.info("State or items check failed - returning False")
            return False
        
        _logger.info("All checks passed - returning True")
        _logger.info("=== _should_apply_payment_fee END ===")
        return True

    def _get_update_prices_lines(self):
        """Exclude payment fee lines from price recomputation."""
        lines = super()._get_update_prices_lines()
        return lines.filtered(lambda line: not line.is_payment_fee)

    def action_confirm(self):
        """Override to ensure payment fee is included before confirmation if order was paid online."""
        # If order has transactions, it means it was paid online, so fee should already be there
        # We don't add it here to avoid double-charging if order is confirmed manually
        return super().action_confirm()


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    is_payment_fee = fields.Boolean(
        string="Is Payment Fee",
        default=False,
        help="Indicates if this line is a payment processing fee"
    )

    def _is_not_sellable_line(self):
        """Exclude payment fee lines from sellable line checks."""
        return self.is_payment_fee or super()._is_not_sellable_line()


# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import _
from odoo.exceptions import ValidationError
from odoo.http import request, route

from odoo.addons.website_sale.controllers import main as website_sale_main
from odoo.addons.website_sale.controllers.payment import PaymentPortal as WebsiteSalePaymentPortal

_logger = logging.getLogger(__name__)


class WebsiteSale(website_sale_main.WebsiteSale):
    """Override website sale controller to add fee when payment page loads."""

    def _get_express_shop_payment_values(self, order, **kwargs):
        """Override to add fee information for express checkout on cart page."""
        values = super()._get_express_shop_payment_values(order, **kwargs)
        
        # When on cart (/shop/cart), we never want a fee line in the order yet.
        # Ensure any existing fee (from a previous payment attempt) is removed
        # so that the cart totals and lines never show the processing fee.
        if order:
            order._remove_payment_fee_line()
            order.selected_payment_provider_id = False

        # Add fee information for display on cart page (message only)
        fee_info = []
        if order:
            # Get providers from payment form values
            providers_sudo = values.get('providers_sudo', request.env['payment.provider'])
            for prov in providers_sudo:
                if prov.payment_fee_enabled and prov.payment_fee_percentage > 0:
                    fee_info.append({
                        'provider_id': prov.id,
                        'provider_name': prov.name,
                        'fee_percentage': prov.payment_fee_percentage,
                    })
        
        values['payment_fee_info'] = fee_info
        return values

    def _get_shop_payment_values(self, order, **kwargs):
        """Override to add fee if provider is already selected and add fee info."""
        # Get payment values from parent first
        values = super()._get_shop_payment_values(order, **kwargs)
        
        # When landing on the payment page without a selected provider,
        # make sure no fee line is present yet. The fee will be added only
        # when the customer explicitly selects a payment method (via JS
        # calling /shop/payment/update_fee).
        if order and not order.selected_payment_provider_id:
            order._remove_payment_fee_line()
        
        # Add fee information for display
        fee_info = []
        if order:
            # Check all available providers for fee info
            providers_sudo = values.get('providers_sudo', request.env['payment.provider'])
            for prov in providers_sudo:
                if prov.payment_fee_enabled and prov.payment_fee_percentage > 0:
                    fee_info.append({
                        'provider_id': prov.id,
                        'provider_name': prov.name,
                        'fee_percentage': prov.payment_fee_percentage,
                    })
        
        values['payment_fee_info'] = fee_info
        return values


class PaymentPortal(WebsiteSalePaymentPortal):
    """Override payment controller to add processing fee before payment."""

    def _get_extra_payment_form_values(self, invoice_id=None, access_token=None, **kwargs):
        """Override to pass invoice_id and sale_order_id to template for JavaScript.
        
        Also tries to detect sale orders or invoices from payment context.
        """
        _logger.info("=== _get_extra_payment_form_values START ===")
        _logger.info("invoice_id=%s, access_token=%s, kwargs=%s", invoice_id, access_token, kwargs)
        
        form_values = super()._get_extra_payment_form_values(
            invoice_id=invoice_id, access_token=access_token, **kwargs
        )
        
        # Get invoice_id from kwargs (account_payment passes it)
        invoice_id = invoice_id or kwargs.get('invoice_id')
        _logger.info("invoice_id after kwargs check: %s", invoice_id)
        
        # Try to detect sale order or invoice from payment context
        # Check if we can find them by amount, partner, and currency
        if not invoice_id and not kwargs.get('sale_order_id'):
            amount = kwargs.get('amount')
            partner_id = kwargs.get('partner_id')
            currency_id = kwargs.get('currency_id')
            _logger.info("Trying to detect document: amount=%s, partner_id=%s, currency_id=%s", 
                        amount, partner_id, currency_id)
            
            if amount and partner_id and currency_id:
                # Try to find sale order
                sale_order = request.env['sale.order'].sudo().search([
                    ('partner_id', '=', partner_id),
                    ('currency_id', '=', currency_id),
                    ('amount_total', '=', amount),
                    ('state', 'in', ('draft', 'sent', 'done')),  # Include 'done' state
                ], limit=1, order='id desc')
                
                if sale_order:
                    _logger.info("Found sale order: ID=%s, name=%s, state=%s", 
                                sale_order.id, sale_order.name, sale_order.state)
                    form_values['sale_order_id'] = sale_order.id
                    invoice_id = None  # Don't check for invoice if we found sale order
                
                # Try to find invoice if no sale order found
                if not sale_order:
                    invoice = request.env['account.move'].sudo().search([
                        ('partner_id', '=', partner_id),
                        ('currency_id', '=', currency_id),
                        ('amount_total', '=', amount),
                        ('move_type', 'in', ('out_invoice', 'out_refund')),
                        ('state', 'in', ('draft', 'posted')),  # Include both states
                    ], limit=1, order='id desc')
                    
                    if invoice:
                        _logger.info("Found invoice: ID=%s, name=%s, state=%s", 
                                    invoice.id, invoice.name, invoice.state)
                        form_values['invoice_id'] = invoice.id
                        invoice_id = invoice.id
        
        # Pass invoice_id if available
        if invoice_id:
            form_values['invoice_id'] = invoice_id
            _logger.info("Setting invoice_id in form_values: %s", invoice_id)
        
        # Also check for sale_order_id in kwargs
        sale_order_id = kwargs.get('sale_order_id')
        if sale_order_id:
            form_values['sale_order_id'] = sale_order_id
            _logger.info("Setting sale_order_id in form_values: %s", sale_order_id)
        
        _logger.info("Final form_values: invoice_id=%s, sale_order_id=%s", 
                    form_values.get('invoice_id'), form_values.get('sale_order_id'))
        _logger.info("=== _get_extra_payment_form_values END ===")
        return form_values

    @route('/payment/update_fee_amount', type='json', auth='public', website=True)
    def payment_update_fee_amount(self, provider_id=None, invoice_id=None, sale_order_id=None, **kwargs):
        """Update payment fee amount when provider is selected on payment form.
        
        This adds the fee product to the sale order or invoice, then returns the updated amount.
        
        :param int provider_id: The payment provider ID
        :param int invoice_id: The invoice ID (if paying invoice)
        :param int sale_order_id: The sale order ID (if paying sale order)
        :return: Updated amount with fee
        :rtype: dict
        """
        _logger.info("=== payment_update_fee_amount START ===")
        _logger.info("provider_id=%s, invoice_id=%s, sale_order_id=%s, kwargs=%s", 
                    provider_id, invoice_id, sale_order_id, kwargs)
        
        provider = None
        if provider_id:
            provider = request.env['payment.provider'].sudo().browse(provider_id).exists()
            if not provider:
                _logger.warning("Provider not found: provider_id=%s", provider_id)
                return {'amount': None, 'error': 'Invalid provider or fee not enabled'}
            if not provider.payment_fee_enabled:
                _logger.warning("Provider fee not enabled: provider_id=%s, name=%s", 
                              provider_id, provider.name)
                return {'amount': None, 'error': 'Invalid provider or fee not enabled'}
            _logger.info("Provider found: ID=%s, name=%s, fee_enabled=%s, fee_percentage=%s", 
                        provider.id, provider.name, provider.payment_fee_enabled, provider.payment_fee_percentage)
        
        amount = None
        fee_amount = 0.0
        currency = None
        
        # Handle invoice payment
        if invoice_id:
            _logger.info("Processing invoice payment: invoice_id=%s", invoice_id)
            invoice = request.env['account.move'].sudo().browse(invoice_id).exists()
            if not invoice:
                _logger.warning("Invoice not found: invoice_id=%s", invoice_id)
            else:
                _logger.info("Invoice found: ID=%s, name=%s, state=%s, amount_total=%s", 
                            invoice.id, invoice.name, invoice.state, invoice.amount_total)
                currency = invoice.currency_id
                # Try to add fee line to invoice (works for draft/posted states)
                # _add_payment_fee_line handles 'posted' state using sudo()
                fee_added = invoice._add_payment_fee_line(provider)
                _logger.info("Fee added to invoice: fee_added=%s", fee_added)
                if fee_added:
                    invoice.invalidate_recordset(['amount_total', 'amount_untaxed', 'amount_tax'])
                    invoice._compute_amount()  # Singular, not plural (invoices use _compute_amount, sale orders use _compute_amounts)
                    amount = invoice.amount_total
                    _logger.info("Invoice amount after fee: amount_total=%s", amount)
                else:
                    # Couldn't add fee line, calculate fee and add to amount
                    fee_amount = invoice._calculate_payment_fee_amount(provider)
                    amount = invoice.amount_total + fee_amount
                    _logger.info("Fee calculated (not added as line): fee_amount=%s, amount=%s", 
                               fee_amount, amount)
        
        # Handle sale order payment
        elif sale_order_id:
            _logger.info("Processing sale order payment: sale_order_id=%s", sale_order_id)
            sale_order = request.env['sale.order'].sudo().browse(sale_order_id).exists()
            if not sale_order:
                _logger.warning("Sale order not found: sale_order_id=%s", sale_order_id)
            else:
                _logger.info("Sale order found: ID=%s, name=%s, state=%s, amount_total=%s, website_id=%s", 
                            sale_order.id, sale_order.name, sale_order.state, sale_order.amount_total, sale_order.website_id)
                currency = sale_order.currency_id
                should_apply = sale_order._should_apply_payment_fee(provider)
                _logger.info("Should apply payment fee: %s", should_apply)
                if should_apply:
                    # Add fee to sale order (works for draft/sent/done states)
                    # _add_payment_fee_line handles 'done' state using sudo()
                    sale_order.selected_payment_provider_id = provider.id if provider else False
                    _logger.info("Set selected_payment_provider_id=%s", sale_order.selected_payment_provider_id)
                    sale_order._add_payment_fee_line(provider)
                    sale_order.invalidate_recordset(['amount_total', 'amount_untaxed', 'amount_tax'])
                    sale_order._compute_amounts()
                    amount = sale_order.amount_total
                    _logger.info("Sale order amount after fee: amount_total=%s", amount)
                else:
                    _logger.warning("Payment fee should NOT be applied for sale order %s", sale_order.name)
        
        if amount is None:
            _logger.error("Could not calculate amount - returning error")
            return {'amount': None, 'error': 'Could not calculate amount'}
        
        result = {
            'amount': amount,
            'fee_amount': fee_amount,
            'currency': currency.name if currency else None,
            'currency_symbol': currency.symbol if currency else '$',
        }
        _logger.info("Returning result: %s", result)
        _logger.info("=== payment_update_fee_amount END ===")
        return result

    @route('/shop/payment/update_fee', type='json', auth='public', website=True)
    def shop_payment_update_fee(self, provider_id=None, **kwargs):
        """Update payment fee when provider is selected on checkout page.
        
        :param int provider_id: The payment provider ID
        :return: Updated order totals
        :rtype: dict
        """
        order_sudo = request.website.sale_get_order()
        if not order_sudo:
            return {'error': _('No order found')}
        
        provider = None
        if provider_id:
            provider = request.env['payment.provider'].sudo().browse(provider_id).exists()
            if not provider:
                return {'error': _('Invalid payment provider')}
            # Store selected provider on order
            order_sudo.selected_payment_provider_id = provider.id
        
        # Add or update payment fee
        order_sudo._add_payment_fee_line(provider)
        
        # Refresh order to get updated values
        order_sudo.invalidate_recordset(['amount_total', 'amount_untaxed', 'amount_tax', 'order_line'])
        order_sudo._compute_amounts()
        
        # Get fee amount
        fee_lines = order_sudo.order_line.filtered('is_payment_fee')
        fee_amount = sum(fee_lines.mapped('price_total')) if fee_lines else 0.0
        
        # Return updated totals
        return {
            'amount_untaxed': order_sudo.amount_untaxed,
            'amount_tax': order_sudo.amount_tax,
            'amount_total': order_sudo.amount_total,
            'has_fee': bool(fee_lines),
            'fee_amount': fee_amount,
        }

    @route('/shop/payment/transaction/<int:order_id>', type='json', auth='public', website=True)
    def shop_payment_transaction(self, order_id, access_token, **kwargs):
        """Override to add payment fee before creating transaction."""
        # Check the order id and the access token first (same as parent)
        try:
            order_sudo = self._document_check_access('sale.order', order_id, access_token)
            from odoo.tools import SQL
            request.env.cr.execute(
                SQL('SELECT 1 FROM sale_order WHERE id = %s FOR NO KEY UPDATE NOWAIT', order_id)
            )
        except Exception:
            # Let parent handle the exception
            return super().shop_payment_transaction(order_id, access_token, **kwargs)
        
        # Get provider from kwargs if available
        provider = None
        if kwargs.get('provider_id'):
            provider = request.env['payment.provider'].sudo().browse(kwargs['provider_id']).exists()
            order_sudo.selected_payment_provider_id = provider.id if provider else False
        
        # Add payment fee if applicable (before amount checks)
        if order_sudo._should_apply_payment_fee(provider):
            order_sudo._add_payment_fee_line(provider)
            # Refresh the order to get updated totals
            order_sudo.invalidate_recordset(['amount_total', 'amount_untaxed', 'amount_tax'])
            order_sudo._compute_amounts()
            # Update the amount in kwargs to match the new total (including fee)
            kwargs['amount'] = order_sudo.amount_total
        
        # Call parent method which will create the transaction with updated amount
        return super().shop_payment_transaction(order_id, access_token, **kwargs)

    def _create_transaction(
        self, provider_id, payment_method_id, token_id, amount, currency_id, partner_id, flow,
        tokenization_requested, landing_route, reference_prefix=None, is_validation=False,
        custom_create_values=None, **kwargs
    ):
        """Override to add payment fee before creating transaction.
        
        Simple logic:
        - If payment is via invoice link → add fee to invoice
        - If payment is via sale order link → add fee to sale order
        """
        _logger.info("=== _create_transaction START ===")
        _logger.info("provider_id=%s, amount=%s, currency_id=%s, partner_id=%s, flow=%s", 
                    provider_id, amount, currency_id, partner_id, flow)
        _logger.info("custom_create_values=%s, kwargs=%s", custom_create_values, kwargs)
        
        from odoo.fields import Command
        
        provider = request.env['payment.provider'].sudo().browse(provider_id).exists() if provider_id else None
        if not provider or not provider.payment_fee_enabled:
            _logger.info("Provider not found or fee not enabled - skipping fee addition")
            return super()._create_transaction(
                provider_id=provider_id,
                payment_method_id=payment_method_id,
                token_id=token_id,
                amount=amount,
                currency_id=currency_id,
                partner_id=partner_id,
                flow=flow,
                tokenization_requested=tokenization_requested,
                landing_route=landing_route,
                reference_prefix=reference_prefix,
                is_validation=is_validation,
                custom_create_values=custom_create_values,
                **kwargs
            )
        
        _logger.info("Provider fee enabled: ID=%s, name=%s, percentage=%s", 
                    provider.id, provider.name, provider.payment_fee_percentage)
        
        # Simple logic: Check what's being paid
        invoice_id = None
        sale_order_id = None
        
        # 1. Check for invoice (invoice payment link)
        if custom_create_values and 'invoice_ids' in custom_create_values:
            invoice_ids_cmd = custom_create_values.get('invoice_ids')
            _logger.info("Found invoice_ids in custom_create_values: %s", invoice_ids_cmd)
            if invoice_ids_cmd and isinstance(invoice_ids_cmd, list):
                for cmd in invoice_ids_cmd:
                    if isinstance(cmd, (list, tuple)) and len(cmd) >= 2:
                        cmd_type = cmd[0]
                        _logger.info("Processing invoice command: cmd_type=%s (type=%s), Command.SET=%s, cmd=%s", 
                                   cmd_type, type(cmd_type), Command.SET, cmd)
                        # Command.SET is an enum with value 6
                        # Compare with both the enum and its integer value for safety
                        if cmd_type == Command.SET or cmd_type == 6:
                            # Command.SET format: (Command.SET, 0, [id1, id2, ...])
                            # The actual IDs are in cmd[2], not cmd[1]
                            if len(cmd) >= 3:
                                cmd_value = cmd[2]
                                _logger.info("Command.SET detected, cmd_value=%s (type=%s)", cmd_value, type(cmd_value))
                                if isinstance(cmd_value, list) and len(cmd_value) > 0:
                                    invoice_id = cmd_value[0]
                                    _logger.info("Extracted invoice_id from Command.SET: %s", invoice_id)
                                    break
                                elif isinstance(cmd_value, int):
                                    invoice_id = cmd_value
                                    _logger.info("Extracted invoice_id from Command.SET (int): %s", invoice_id)
                                    break
                        elif cmd_type in (Command.LINK, Command.CREATE) or cmd_type in (4, 1):
                            # Command.link/create format: (Command.LINK, id) or (Command.CREATE, {...})
                            if len(cmd) >= 2:
                                cmd_value = cmd[1]
                                if isinstance(cmd_value, int):
                                    invoice_id = cmd_value
                                    _logger.info("Extracted invoice_id from Command.link/create: %s", invoice_id)
                                    break
        
        # 2. Check for sale order (sale order payment link)
        if not invoice_id and custom_create_values and 'sale_order_ids' in custom_create_values:
            sale_order_ids_cmd = custom_create_values.get('sale_order_ids')
            _logger.info("Found sale_order_ids in custom_create_values: %s", sale_order_ids_cmd)
            if sale_order_ids_cmd and isinstance(sale_order_ids_cmd, list):
                for cmd in sale_order_ids_cmd:
                    if isinstance(cmd, (list, tuple)) and len(cmd) >= 2:
                        cmd_type = cmd[0]
                        _logger.info("Processing sale order command: cmd_type=%s (type=%s), Command.SET=%s, cmd=%s", 
                                   cmd_type, type(cmd_type), Command.SET, cmd)
                        # Command.SET is an enum with value 6
                        # Compare with both the enum and its integer value for safety
                        if cmd_type == Command.SET or cmd_type == 6:
                            # Command.SET format: (Command.SET, 0, [id1, id2, ...])
                            # The actual IDs are in cmd[2], not cmd[1]
                            if len(cmd) >= 3:
                                cmd_value = cmd[2]
                                _logger.info("Command.SET detected, cmd_value=%s (type=%s)", cmd_value, type(cmd_value))
                                if isinstance(cmd_value, list) and len(cmd_value) > 0:
                                    sale_order_id = cmd_value[0]
                                    _logger.info("Extracted sale_order_id from Command.SET: %s", sale_order_id)
                                    break
                                elif isinstance(cmd_value, int):
                                    sale_order_id = cmd_value
                                    _logger.info("Extracted sale_order_id from Command.SET (int): %s", sale_order_id)
                                    break
                        elif cmd_type in (Command.LINK, Command.CREATE) or cmd_type in (4, 1):
                            # Command.link/create format: (Command.LINK, id) or (Command.CREATE, {...})
                            if len(cmd) >= 2:
                                cmd_value = cmd[1]
                                if isinstance(cmd_value, int):
                                    sale_order_id = cmd_value
                                    _logger.info("Extracted sale_order_id from Command.link/create: %s", sale_order_id)
                                    break
        
        # 3. Fallback: check kwargs
        if not invoice_id and not sale_order_id:
            invoice_id = kwargs.get('invoice_id')
            sale_order_id = kwargs.get('sale_order_id')
        
        _logger.info("Detected: invoice_id=%s, sale_order_id=%s", invoice_id, sale_order_id)
        
        # Add fee based on what's being paid
        if invoice_id:
            # Payment via invoice link → add fee to invoice
            _logger.info("Case: Invoice payment - invoice_id=%s", invoice_id)
            invoice = request.env['account.move'].sudo().browse(invoice_id).exists()
            if invoice:
                _logger.info("Invoice found: ID=%s, name=%s, state=%s", 
                           invoice.id, invoice.name, invoice.state)
                fee_added = invoice._add_payment_fee_line(provider)
                _logger.info("Fee added to invoice: fee_added=%s", fee_added)
                
                if fee_added:
                    invoice.invalidate_recordset(['amount_total', 'amount_untaxed', 'amount_tax'])
                    invoice._compute_amount()  # Singular, not plural (invoices use _compute_amount, sale orders use _compute_amounts)
                    amount = invoice.amount_total
                    _logger.info("Updated transaction amount from invoice: amount=%s", amount)
                else:
                    # Couldn't add fee line - calculate fee and add to transaction amount
                    fee_amount = invoice._calculate_payment_fee_amount(provider)
                    amount = (amount or 0.0) + fee_amount
                    _logger.info("Fee calculated (not added as line): fee_amount=%s, amount=%s", 
                               fee_amount, amount)
            else:
                _logger.warning("Invoice not found: invoice_id=%s", invoice_id)
        
        elif sale_order_id:
            # Payment via sale order link → add fee to sale order
            _logger.info("Case: Sale order payment - sale_order_id=%s", sale_order_id)
            sale_order = request.env['sale.order'].sudo().browse(sale_order_id).exists()
            if sale_order:
                _logger.info("Sale order found: ID=%s, name=%s, state=%s", 
                           sale_order.id, sale_order.name, sale_order.state)
                sale_order.selected_payment_provider_id = provider.id
                
                if sale_order._should_apply_payment_fee(provider):
                    sale_order._add_payment_fee_line(provider)
                    sale_order.invalidate_recordset(['amount_total', 'amount_untaxed', 'amount_tax'])
                    sale_order._compute_amounts()
                    amount = sale_order.amount_total
                    _logger.info("Updated transaction amount from sale order: amount=%s", amount)
                else:
                    _logger.warning("Payment fee should NOT be applied for sale order %s", sale_order.name)
            else:
                _logger.warning("Sale order not found: sale_order_id=%s", sale_order_id)
        else:
            _logger.info("No invoice or sale order found - skipping fee addition")
        
        _logger.info("Final transaction amount: amount=%s", amount)
        _logger.info("=== _create_transaction END ===")
        # Call parent to create the transaction
        return super()._create_transaction(
            provider_id=provider_id,
            payment_method_id=payment_method_id,
            token_id=token_id,
            amount=amount,
            currency_id=currency_id,
            partner_id=partner_id,
            flow=flow,
            tokenization_requested=tokenization_requested,
            landing_route=landing_route,
            reference_prefix=reference_prefix,
            is_validation=is_validation,
            custom_create_values=custom_create_values,
            **kwargs
        )


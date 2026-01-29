# Website Sale Payment Processing Fee

This module adds a configurable card processing fee for online payments on website orders in Odoo 18. The fee is configured per payment provider, allowing different fees for different payment methods (e.g., 4% for card payments, 0% for bank transfers).

## Features

- **Per-Provider Fee Configuration**: Configure different fee percentages for each payment provider
- **Automatic Fee Calculation**: Adds processing fee automatically when a payment provider is selected on checkout
- **Real-Time Updates**: Fee is added and displayed immediately when customer selects a payment method
- **Separate Line Item**: Fee is added as a separate line item on the order, similar to delivery fees
- **Website Orders Only**: Fee only applies to orders placed through the website
- **Smart Calculation**: Fee is calculated on order subtotal excluding delivery charges
- **No Global Settings**: Simple, provider-based configuration - no confusing global settings

## Installation

1. Copy this module to your Odoo addons directory
2. Update the apps list in Odoo
3. Install the "Website Sale Payment Processing Fee" module

## Configuration

### Per-Payment Provider Configuration

1. Go to **Accounting > Configuration > Payment Providers**
2. Select or create a payment provider (e.g., Stripe, PayPal, Bank Transfer, Demo)
3. In the provider form, scroll to the **Payment Processing Fee** section:
   - **Enable Payment Processing Fee**: Check to enable fee for this provider
   - **Payment Fee Percentage**: Set the fee percentage (e.g., 4.0 for 4%)
   - **Payment Fee Product**: Optionally select a specific product to use for the fee line item
     - If not specified, a default "Card Processing Fee" product will be created automatically

### Example Configuration

- **Stripe Provider**: Enable fee, set 4.0% → Customers pay 4% fee when using Stripe
- **PayPal Provider**: Enable fee, set 3.5% → Customers pay 3.5% fee when using PayPal
- **Bank Transfer Provider**: Disable fee → No fee for bank transfers

## How It Works

1. **On Checkout Page**:
   - When a customer selects a payment provider on the checkout page
   - JavaScript detects the selection and calls the update fee route
   - The fee is calculated based on the selected provider's settings
   - A fee line item is added to the order
   - The page refreshes to show the updated total including the fee

2. **Fee Calculation**:
   - Fee is calculated on the order subtotal (excluding delivery and existing fees)
   - Formula: `Fee Amount = (Order Subtotal - Delivery) × (Provider Fee % / 100)`
   - Fee is rounded to the currency's precision

3. **Fee Line Item**:
   - The fee appears as a separate line item: "Card Processing Fee (X%) - Provider Name"
   - The line is marked with `is_payment_fee = True` to distinguish it from regular order lines
   - The fee is included in the order total shown to the customer
   - The fee appears in sale order PDFs and all order views

## Technical Details

### Module Information
- **Module Name**: `ox_website_sale_payment_fee`
- **Dependencies**: `website_sale`, `payment`
- **Odoo Version**: 18.0

### Models Extended

#### `payment.provider`
- **Fields Added**:
  - `payment_fee_enabled` (Boolean): Enable/disable fee for this provider
  - `payment_fee_percentage` (Float): Fee percentage (e.g., 4.0 for 4%)
  - `payment_fee_product_id` (Many2one): Optional product for fee line item

#### `sale.order`
- **Fields Added**:
  - `has_payment_fee` (Boolean, computed): Indicates if order has a payment fee line
  - `selected_payment_provider_id` (Many2one): Tracks the selected payment provider

- **Methods Added**:
  - `_get_payment_fee_provider()`: Get the payment provider for fee calculation
  - `_get_payment_fee_product(provider)`: Get or create the fee product
  - `_get_payment_fee_percentage(provider)`: Get fee percentage from provider
  - `_calculate_payment_fee_amount(provider)`: Calculate the fee amount
  - `_add_payment_fee_line(provider)`: Add or update fee line on order
  - `_remove_payment_fee_line()`: Remove fee line from order
  - `_should_apply_payment_fee(provider)`: Determine if fee should be applied
  - `_get_update_prices_lines()`: Exclude fee lines from price recomputation

#### `sale.order.line`
- **Fields Added**:
  - `is_payment_fee` (Boolean): Marks the line as a payment processing fee

### Controllers Extended

#### `website_sale.controllers.payment.PaymentPortal`
- **Routes Added**:
  - `/shop/payment/update_fee` (JSON): Updates fee when provider is selected
  - Overrides `/shop/payment/transaction/<int:order_id>`: Ensures fee is included before transaction

### JavaScript

#### `payment_fee.js`
- Listens for payment provider selection changes
- Automatically calls `/shop/payment/update_fee` when provider is selected
- Prevents infinite reload loops using sessionStorage
- Uses Odoo 18 ES6 module syntax

### Views

#### `payment_provider_views.xml`
- Adds "Payment Processing Fee" section to payment provider form
- Fields are only visible when provider is not disabled

## Fee Calculation Details

The fee is calculated as:
```
Fee Amount = (Order Subtotal - Delivery - Existing Fees) × (Provider Fee Percentage / 100)
```

Where:
- **Order Subtotal**: Sum of all order line `price_subtotal` (excluding delivery and fee lines)
- **Delivery**: Shipping/delivery charges
- **Existing Fees**: Any existing payment fee lines (to avoid recursion)
- **Provider Fee Percentage**: The percentage configured for the selected payment provider

The fee is rounded to the currency's precision.

## Use Cases

### Card Payments with Fee
- **Provider**: Stripe, PayPal, etc.
- **Configuration**: Enable fee, set 4.0%
- **Result**: Customer pays 4% processing fee on checkout

### Bank Transfer without Fee
- **Provider**: Bank Transfer
- **Configuration**: Disable fee (or leave at 0%)
- **Result**: No fee applied for bank transfers

### Different Fees for Different Providers
- **Stripe**: 4.0% fee
- **PayPal**: 3.5% fee
- **Bank Transfer**: 0% fee (disabled)
- Each provider can have its own fee percentage

### Custom Fee Product
- Set a custom product in provider settings
- Useful if you want different fee products for different providers
- If not set, default "Card Processing Fee" product is used

## Workflow

1. **Customer adds items to cart** → No fee yet
2. **Customer proceeds to checkout** → No fee yet
3. **Customer selects payment provider** → Fee is calculated and added
4. **Order summary updates** → Shows fee line and updated total
5. **Customer completes payment** → Fee is included in transaction amount
6. **Order is confirmed** → Fee appears in sale order and PDF

## Important Notes

- **Provider Selection Required**: Fee is only added when a payment provider is selected on the checkout page
- **No Fee for Manual Orders**: If an order is manually confirmed without online payment, no fee is added
- **Fee Product Auto-Creation**: If no fee product is specified, a default product is automatically created
- **Fee Excluded from Price Recalculation**: Fee lines are excluded from automatic price recomputation (like delivery lines)
- **Concurrent Updates**: Database serialization errors may occur with concurrent requests but are automatically retried by Odoo

## Troubleshooting

### Fee Shows as $0.00
- Check that the payment provider has "Enable Payment Processing Fee" checked
- Verify the fee percentage is set (e.g., 4.0)
- Ensure the order has items (base_amount > 0)
- Check Odoo logs for calculation details

### Fee Not Appearing on Checkout
- Ensure JavaScript is loaded (check browser console)
- Verify payment provider is selected
- Check that provider has fee enabled
- Look for JavaScript errors in browser console

### Infinite Page Reload
- Clear browser cache and sessionStorage
- Check browser console for errors
- Ensure latest module version is installed

### Testing

1. Create a test order on the website
2. Add items to cart
3. Proceed to checkout
4. Select a payment provider with fee enabled
5. Verify fee appears in order summary
6. Complete the order
7. Check sale order PDF includes the fee

## License

LGPL-3

## Support

For issues or questions, please check:
- Odoo logs for error messages
- Browser console for JavaScript errors
- Payment provider configuration
- Order state and payment provider selection

## Changelog

### Version 18.0.1.0.0
- Initial release
- Per-provider fee configuration
- Real-time fee updates on checkout
- Automatic fee calculation
- Support for custom fee products

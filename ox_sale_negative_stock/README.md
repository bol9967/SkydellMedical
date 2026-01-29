# Sale Negative Stock Control

## Overview

This Odoo 18 module prevents products with zero on-hand quantity from being added to sale orders. This helps prevent selling items that are not available in stock, improving order accuracy and customer satisfaction.

**Important:** This module only affects the **Sale app**. Website/e-commerce orders are not affected and continue to use their own stock control settings (like `allow_out_of_stock_order`).

## Features

### 1. Stock-Based Product Filtering
- Automatically hides products with zero stock (`qty_available = 0`) from product selection in sale order lines
- Only applies to physical products (Goods) with stock tracking enabled
- Service products, combo products, and products without stock tracking are always visible

### 2. Configurable Settings
- **No Negative Stock Sale**: Enable/disable the entire feature
- **Display Zero Stock Products in Search**: When enabled, shows zero-stock products in search but still prevents adding them (validation applies)
- **Show On Hand Qty in Sale Order Line**: Displays an "On Hand Qty" column in sale order lines

### 3. On Hand Quantity Column
When enabled, displays stock information in sale order lines:
- **"Service"** - for service products
- **"Combo"** - for combo products  
- **"Not Tracked"** - for physical products without stock tracking
- **Actual quantity** - for physical products with stock tracking enabled

## Installation

1. Copy the module to your Odoo addons directory
2. Update the apps list in Odoo
3. Search for "Sale Negative Stock Control"
4. Click Install

### Dependencies
- `sale` - Sales module
- `stock` - Inventory/Stock module

## Configuration

Navigate to: **Settings → Sales → Stock Control**

### Settings Available:

#### 1. No Negative Stock Sale
**Description:** When enabled, products that are out of stock (quantity = 0) will not be visible in the search list when selecting products in sale orders (Sale app only, not website/e-commerce). This prevents selling items that are not available. Service products and products without stock tracking are always shown.

**What gets hidden from search:**
- Physical products (Goods) that have stock tracking enabled and are currently out of stock (quantity = 0)

**What always remains visible in search:**
- Service products (like delivery fees, consulting services, etc.)
- Combo products
- Physical products without stock tracking
- Physical products with stock tracking that have available inventory

#### 2. Display Zero Stock Products in Search
**Description:** When enabled, out-of-stock products will be visible in the product search list, but you still cannot add them to sale orders. Use this to see products for reference while still preventing them from being sold.

**Note:** This setting only appears when "No Negative Stock Sale" is enabled.

#### 3. Show On Hand Qty in Sale Order Line
**Description:** When enabled, displays an 'On Hand Qty' column in sale order lines. The column shows:
- **"Service"** - when the product type is Service
- **"Combo"** - when the product type is Combo
- **"Not Tracked"** - when the product is a physical product (Goods) without stock tracking enabled
- **Actual stock quantity** - when the product is a physical product (Goods) with stock tracking enabled

## Usage

### Basic Usage

1. **Enable the feature:**
   - Go to Settings → Sales → Stock Control
   - Enable "No Negative Stock Sale"

2. **Create a Sale Order:**
   - When adding products to a sale order line, only products with available stock will appear in the search
   - Products with zero stock will be automatically filtered out

3. **View Stock Information (Optional):**
   - Enable "Show On Hand Qty in Sale Order Line" to see stock quantities directly in the order lines

### Advanced Usage

**Display Zero Stock in Search:**
- Enable "Display Zero Stock Products in Search" to see out-of-stock products in the search list
- These products will be visible but cannot be added (validation prevents it)
- Useful for reference or when planning future orders

## Technical Details

### Models Extended

1. **`product.product`**
   - Overrides `_name_search` method to filter products based on stock availability
   - Detects sale context vs website context to avoid conflicts

2. **`product.template`**
   - Overrides `_search` method for "Search More..." dialog
   - Applies same filtering logic as product.product

3. **`sale.order.line`**
   - Adds validation to prevent adding zero-stock products
   - Adds computed field `on_hand_qty_display` for stock information display
   - Adds computed field `show_on_hand_qty_column` for column visibility control

4. **`sale.order`**
   - Adds computed field `show_on_hand_qty` for form view column visibility

5. **`res.config.settings`**
   - Adds three configuration settings for module control

### Filtering Logic

The module filters products based on the following rules:

**Products that are ALWAYS visible:**
- Service products (`type = 'service'`)
- Combo products (`type = 'combo'`)
- Physical products without stock tracking (`type = 'consu'` AND `is_storable = False`)

**Products that are filtered (hidden when stock = 0):**
- Physical products with stock tracking (`type = 'consu'` AND `is_storable = True` AND `qty_available = 0`)

### Website/E-commerce Compatibility

The module automatically detects and excludes website/e-commerce contexts:
- Checks for `website_id` in context
- Checks if sale order has `website_id` set
- Checks if sale order line belongs to a website order
- When website context is detected, the filtering logic is skipped, allowing native `website_sale` behavior

This ensures:
- Sale app uses this module's filtering
- Website/e-commerce uses native `allow_out_of_stock_order` setting
- No conflicts between the two systems

## Views Modified

1. **Sale Order Form View**
   - Adds "On Hand Qty" column to order lines (when enabled)
   - Column positioned after "Quantity" column

2. **Configuration Settings View**
   - Adds "Stock Control" block in Sales settings
   - Contains all three configuration options

## Validation

The module includes validation at multiple levels:

1. **Search Level**: Products filtered from search results
2. **Selection Level**: Validation when product is selected via `@api.onchange`
3. **Create/Write Level**: Validation in `create` and `write` methods using `@api.constrains`

## Troubleshooting

### Products still visible when they should be hidden

1. Check that "No Negative Stock Sale" is enabled in Settings
2. Verify the product type is `consu` (Goods)
3. Verify `is_storable = True` for the product
4. Check that `qty_available = 0` for the product
5. Ensure you're in the Sale app, not website/e-commerce

### On Hand Qty column not showing

1. Enable "Show On Hand Qty in Sale Order Line" in Settings
2. Refresh the browser page
3. Check if the column is hidden (click column visibility toggle)

### Website orders affected

This should not happen. If it does:
1. Verify the module is detecting website context correctly
2. Check that website orders have `website_id` set
3. Review the context detection logic in `product_product.py` and `product_template.py`

## Version History

### Version 18.0.1.0.0
- Initial release
- Basic zero-stock filtering
- Configurable settings
- On Hand Qty column display
- Website/e-commerce compatibility

## Support

For issues or questions:
1. Check the Troubleshooting section above
2. Review Odoo logs for error messages
3. Verify module dependencies are installed
4. Ensure Odoo 18 compatibility

## License

LGPL-3

## Author

Custom Development

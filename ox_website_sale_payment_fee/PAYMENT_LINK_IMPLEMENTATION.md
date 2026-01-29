# Card Processing Fee Implementation for Payment Links

## Overview

This document outlines the implementation approach for handling card processing fees when customers pay via payment links generated from **Sale Orders** and **Invoices**.

## Problem Statement

Currently, the card processing fee works correctly on the website checkout page, but it was not being applied when customers paid using:
- Payment links generated directly from Sale Orders (without invoices)
- Payment links generated from Invoices (via "Generate a Payment Link" action)

## Solution Approach

We will implement a comprehensive solution that automatically detects the payment context and applies the fee appropriately:

### Scenario 1: Payment Link from Sale Order (No Invoice Created)

**When it happens:**
- A payment link is generated directly from a Sale Order
- The sale order is still in draft or sent state
- No invoice has been created yet

**What we do:**
1. Detect that the payment is for a sale order
2. Check if the selected payment provider has card processing fee enabled
3. **Add the fee as a line item directly to the Sale Order**
4. Calculate the fee based on the order total (excluding delivery charges)
5. Update the payment transaction amount to include the fee
6. The fee will appear as "Card Processing Fee" on the sale order

**Result:**
- Customer pays the correct amount (order total + processing fee)
- Fee is visible on the sale order document
- When invoice is created later, the fee will be included automatically

---

### Scenario 2: Payment Link from Invoice (Draft Invoice)

**When it happens:**
- An invoice has been created from a sale order
- The invoice is still in draft state (not posted)
- A payment link is generated from this invoice

**What we do:**
1. Detect that the payment is for an invoice
2. Find the linked sale order (if exists)
3. Check if the selected payment provider has card processing fee enabled
4. **Add the fee as a line item directly to the Invoice**
5. Calculate the fee based on the invoice total (excluding delivery and existing fees)
6. Update the payment transaction amount to match the invoice total (now including fee)

**Result:**
- Customer pays the correct amount (invoice total + processing fee)
- Fee appears as a separate line item on the invoice
- Invoice total reflects the fee
- Proper accounting records maintained

---

### Scenario 3: Payment Link from Invoice (Posted Invoice)

**When it happens:**
- An invoice has been created and posted (confirmed)
- A payment link is generated from this posted invoice
- Invoice lines cannot be modified after posting

**What we do:**
1. Detect that the payment is for a posted invoice
2. Check if the selected payment provider has card processing fee enabled
3. Calculate the fee based on the invoice total
4. **Add the fee amount to the payment transaction** (cannot add line to posted invoice)
5. Customer pays invoice amount + processing fee

**Result:**
- Customer pays the correct amount (invoice + fee)
- Fee is collected but not shown as invoice line (due to posting restrictions)
- Transaction amount includes the fee

---

### Scenario 4: Payment Link from Invoice (No Sale Order Link)

**When it happens:**
- An invoice exists but is not linked to a sale order
- Payment link is generated from this invoice

**What we do:**
1. Detect the invoice payment
2. Check if the selected payment provider has card processing fee enabled
3. If invoice is draft: Add fee line to invoice
4. If invoice is posted: Add fee to transaction amount
5. Calculate fee based on invoice amount

**Result:**
- Fee is applied correctly regardless of sale order link
- Proper handling for all invoice types

---

## Technical Implementation Details

### Key Components

1. **Sale Order Model Extension** (`sale_order.py`)
   - Methods to add/remove fee lines on sale orders
   - Fee calculation based on order totals
   - Provider-specific fee configuration

2. **Invoice Model Extension** (`account_move.py`) - NEW
   - Methods to add/remove fee lines on invoices
   - Fee calculation based on invoice totals
   - Handles both draft and posted invoices

3. **Payment Controller Extension** (`payment.py`)
   - Detects payment context (sale order vs invoice)
   - Routes to appropriate fee handling logic
   - Updates transaction amounts automatically

### Detection Logic

The system automatically detects:
- **Sale Order Payments**: Via `sale_order_ids` in transaction data
- **Invoice Payments**: Via `invoice_ids` in transaction data
- **Sale Order from Invoice**: Links invoices to sale orders via:
  - Invoice line → Sale line → Sale order
  - Invoice origin field (sale order name)

### Fee Calculation

- **Base Amount**: Order/Invoice total excluding:
  - Delivery/shipping charges
  - Existing payment fee lines
  - Display-only lines (section/note lines)

- **Fee Formula**: `Base Amount × (Fee Percentage / 100)`
- **Rounding**: Rounded to currency precision

---

## Benefits

1. **Automatic Fee Application**
   - No manual intervention required
   - Fee is applied automatically when payment link is used

2. **Proper Documentation**
   - Fee appears on sale orders and invoices (when possible)
   - Clear line item: "Card Processing Fee (X%) - Provider Name"
   - Maintains audit trail

3. **Flexible Configuration**
   - Per-provider fee percentage
   - Provider-specific fee products
   - Enable/disable per provider

4. **Accurate Accounting**
   - Fee is properly recorded in accounting
   - Transaction amounts match document totals
   - No discrepancies between payment and invoice

5. **Customer Transparency**
   - Fee is visible on documents
   - Customer knows exactly what they're paying
   - No hidden charges

---

## Configuration

The fee is configured per payment provider:

1. Go to **Accounting → Configuration → Payment Providers**
2. Select a payment provider (e.g., Stripe, PayPal)
3. Enable "Payment Fee Enabled"
4. Set "Payment Fee Percentage" (e.g., 4.0 for 4%)
5. Optionally select a specific "Payment Fee Product"

---

## Testing Scenarios

After implementation, please test:

1. ✅ Generate payment link from draft sale order → Pay → Verify fee on order
2. ✅ Generate payment link from sent sale order → Pay → Verify fee on order
3. ✅ Create invoice from sale order → Generate payment link → Pay → Verify fee on invoice
4. ✅ Post invoice → Generate payment link → Pay → Verify fee in transaction
5. ✅ Generate payment link from invoice without sale order → Pay → Verify fee applied
6. ✅ Switch payment providers → Verify correct fee percentage applied
7. ✅ Return to cart after payment attempt → Verify fee removed from cart

---

## Notes

- Fee is only applied when payment provider has fee enabled
- Fee calculation excludes delivery charges
- Fee cannot be added to posted invoices (Odoo restriction), but is added to transaction amount
- Fee product is automatically created if it doesn't exist
- Existing fee products are reused (no duplicates created)

---

## Support

If you encounter any issues or have questions about the implementation, please contact the development team.


# Debugging Manual Payment Registration Issue

## Problem
Module works fine on Odoo.sh but doesn't create POs when payment is manually registered on client server (installed via .deb).

## Changes Made

### 1. Improved Invoice Detection (`account_payment.py`)
- Enhanced invoice detection to check multiple sources:
  - `reconciled_invoice_ids`: Already reconciled invoices
  - `invoice_ids`: Explicitly linked invoices
  - Payment move lines: Invoices linked via reconciliation on move lines
- Added comprehensive logging to track which invoices are found

### 2. Enhanced Payment State Checking
- Forces recomputation of `payment_state` before checking
- Added fallback to trigger invoice write() method if payment_state isn't updated yet
- Better error handling and logging

### 3. Improved Account Move Write Method (`account_move.py`)
- Better detection of payment_state changes (even when not in vals)
- Forces recomputation of payment_state before processing
- Enhanced error handling

### 4. Added Manual Processing Method
- New method `action_process_dropship_manually()` on account.move
- Can be called manually as a fallback/debugging tool

## Debugging Steps

### Step 1: Check Odoo Logs
After manually registering a payment, check the Odoo logs for messages like:
```
Payment <name> posted, found X related customer invoices for dropship processing
Invoice <name> payment_state after recompute: <state>
Invoice <name> is now <state> after payment <name>, triggering dropship processing
```

### Step 2: Verify Invoice Detection
If you see "no customer invoices found", check:
- Is the payment linked to invoices? (Check `payment.invoice_ids`)
- Is reconciliation happening? (Check `payment.reconciled_invoice_ids`)
- Check payment move lines for linked invoices

### Step 3: Check Payment State
If invoice is found but payment_state is not 'paid' or 'in_payment':
- Reconciliation might not have completed yet
- Check if invoice is actually reconciled
- The write() method should catch this when payment_state changes

### Step 4: Manual Testing
1. Register a payment manually
2. Check logs immediately after
3. If no PO created, try:
   - Wait a few seconds and check again (reconciliation might be delayed)
   - Manually call `invoice.action_process_dropship_manually()` via Odoo shell
   - Check if invoice payment_state is actually 'paid' or 'in_payment'

### Step 5: Odoo Shell Debugging
```python
# In Odoo shell (odoo shell -d erp)
payment = env['account.payment'].search([('name', '=', 'PAYMENT_NAME')], limit=1)
print(f"Payment: {payment.name}")
print(f"Invoice IDs: {payment.invoice_ids.mapped('name')}")
print(f"Reconciled Invoice IDs: {payment.reconciled_invoice_ids.mapped('name')}")

# Check invoice payment state
invoice = payment.invoice_ids[0] if payment.invoice_ids else None
if invoice:
    invoice.invalidate_recordset(['payment_state'])
    invoice._compute_payment_state()
    print(f"Invoice: {invoice.name}, Payment State: {invoice.payment_state}")
    
    # Manually trigger processing
    invoice._process_dropship_for_paid_invoice()
```

## Common Issues

### Issue 1: Invoices Not Linked
**Symptom**: Log shows "no customer invoices found"
**Solution**: 
- Verify payment is linked to invoices during creation
- Check if reconciliation happened
- Check payment move lines

### Issue 2: Payment State Not Updated
**Symptom**: Invoice found but payment_state is not 'paid' or 'in_payment'
**Solution**:
- Reconciliation might be delayed
- Check if invoice is actually reconciled
- The write() method should catch this when payment_state changes

### Issue 3: Module Not Installed/Upgraded
**Symptom**: No logs at all
**Solution**:
- Verify module is installed: `odoo-bin -d erp -u ox_sale_dropship_postpaid`
- Check if module is in addons path
- Restart Odoo server

### Issue 4: Dropship Route Not Found
**Symptom**: Log shows "No dropship route found"
**Solution**:
- Verify dropship route exists: `env['stock.route'].search([('name', 'ilike', 'dropship')])`
- Check route configuration

## Testing Checklist

- [ ] Module is installed and upgraded
- [ ] Odoo server restarted after upgrade
- [ ] Dropship route exists
- [ ] Sale order has dropship lines
- [ ] Invoice is created from sale order
- [ ] Payment is manually registered and linked to invoice
- [ ] Payment is posted (action_post)
- [ ] Invoice payment_state becomes 'paid' or 'in_payment'
- [ ] Logs show processing messages
- [ ] Purchase order is created
- [ ] Purchase order is confirmed
- [ ] Vendor email is sent

## Next Steps if Still Not Working

1. Enable debug mode in Odoo and check logs
2. Add breakpoints in `account_payment.py` action_post() method
3. Check if there are any other modules interfering
4. Compare Odoo.sh environment with client server:
   - Odoo version
   - Installed modules
   - Configuration settings
5. Test with a simple sale order → invoice → payment flow
6. Check database for any constraints or triggers that might interfere


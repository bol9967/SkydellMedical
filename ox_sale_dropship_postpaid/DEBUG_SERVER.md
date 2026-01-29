# Debug Manual Payment Issue on Server

## Quick Start

### Step 1: Run Diagnostics

On your server, run:

```bash
# Navigate to Odoo directory
cd /path/to/odoo  # Usually /usr/lib/odoo or /opt/odoo

# Run diagnostics (copy diagnose_server_issue.py to server first)
./odoo-bin shell -d erp --no-http < diagnose_server_issue.py
```

### Step 2: Or Use Quick Test

```bash
# Start Odoo shell
./odoo-bin shell -d erp --no-http

# Then paste the code from quick_test.py
```

### Step 3: Check Enhanced Logs

After upgrading the module with enhanced logging, manually register a payment and check logs:

```bash
# Watch logs in real-time
tail -f /var/log/odoo/odoo.log | grep -i "ox_sale_dropship_postpaid"

# Or check journal
journalctl -u odoo -f | grep -i "ox_sale_dropship_postpaid"
```

Look for these log messages:
- `ox_sale_dropship_postpaid: action_post() called for X payment(s)`
- `Payment X: Checking for invoices...`
- `Payment X posted, found X related customer invoices`
- `No customer invoices found`

## What the Diagnostics Will Show

The diagnostic script will check:

1. ✅ **Module Installation**: Is module installed and loaded?
2. ✅ **Model Availability**: Are all required models available?
3. ✅ **Method Existence**: Do our custom methods exist?
4. ✅ **Payment Analysis**: What invoices are linked to the payment?
5. ✅ **Payment State**: Are invoices actually paid/in_payment?
6. ✅ **Dropship Lines**: Are there dropship lines in sale orders?
7. ✅ **PO Creation**: Are purchase orders being created?

## Common Issues Found

### Issue 1: No Invoices Linked
```
Payment X posted, but no customer invoices found.
reconciled_invoice_ids=0, invoice_ids=0
```

**Cause**: Payment was created without selecting invoices

**Solution**: 
- When manually registering payment, make sure to select invoices in the payment wizard
- Check if reconciliation happened after payment posting

### Issue 2: Payment State Not Updated
```
Invoice X payment_state is Y (not paid/in_payment yet)
```

**Cause**: Reconciliation hasn't completed or payment_state not recomputed

**Solution**:
- Wait a few seconds for reconciliation
- Manually reconcile if needed
- The account_move write() method should catch this

### Issue 3: Module Not Loaded
```
Model 'account.payment' method 'action_post' NOT found
```

**Cause**: Module not installed or not upgraded

**Solution**:
```bash
./odoo-bin -d erp -u ox_sale_dropship_postpaid --stop-after-init
# Restart Odoo
```

## Enhanced Logging Added

The updated code now includes detailed logging:

- When `action_post()` is called
- How many invoices are found via each method
- Payment state after recomputation
- Whether processing is triggered
- Any errors during processing

## Compare with Odoo.sh

To understand why it works on odoo.sh:

1. **Check Odoo version**: Both should be same version
2. **Check module version**: Same module code?
3. **Check payment workflow**: How are payments created?
4. **Check logs on odoo.sh**: What do logs show there?

## Next Steps

1. **Run diagnostics** on your server
2. **Share the output** - this will show exactly what's happening
3. **Check logs** after manually registering a payment
4. **Compare** with odoo.sh behavior

## Files Created

- `diagnose_server_issue.py` - Full diagnostic script
- `quick_test.py` - Quick inline test
- `QUICK_DEBUG.md` - Quick reference guide

## After Running Diagnostics

Share the output and we can:
1. Identify the exact issue
2. Fix the code if needed
3. Provide specific solution for your server


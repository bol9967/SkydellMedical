# Fix for Manual Payment Registration Issue

## Problem
Module works on Odoo.sh but doesn't create POs when payment is manually registered on client server (.deb installation).

## Changes Made

### 1. Improved Invoice Detection (`account_payment.py`)
- **Priority-based detection**: Checks `invoice_ids` first (most reliable for manual payments)
- **Simplified reconciliation check**: Only checks move lines if invoices not found via direct links
- **Better logging**: Added detailed warnings when invoices aren't found, including partner and amount info
- **Fallback detection**: Suggests potential invoices by partner and date

### 2. Enhanced Payment State Handling
- Forces recomputation of `payment_state` before checking
- Better error handling and logging
- Fallback to trigger invoice `write()` if payment_state isn't updated yet

### 3. Improved Account Move Write Method (`account_move.py`)
- Better detection of payment_state changes
- Forces recomputation before processing
- Added manual processing method `action_process_dropship_manually()`

## Installation Steps

1. **Copy updated files to client server:**
   ```bash
   # On client server, navigate to addons directory
   cd /path/to/odoo/addons
   
   # Copy the updated module
   # (or use git pull if using version control)
   ```

2. **Upgrade the module:**
   ```bash
   # Stop Odoo service
   sudo systemctl stop odoo
   
   # Upgrade module
   sudo -u odoo /usr/bin/odoo-bin -d erp -u ox_sale_dropship_postpaid --stop-after-init
   
   # Or if using systemd service:
   sudo -u odoo /usr/bin/odoo-bin -d erp -u ox_sale_dropship_postpaid --stop-after-init
   
   # Start Odoo service
   sudo systemctl start odoo
   ```

3. **Check Odoo logs:**
   ```bash
   # Watch logs in real-time
   sudo tail -f /var/log/odoo/odoo.log
   
   # Or check journal if using systemd
   sudo journalctl -u odoo -f
   ```

## Debugging Steps

### Step 1: Test Manual Payment Registration
1. Create a sale order with dropship products
2. Create invoice from sale order
3. Manually register a payment for the invoice
4. **IMPORTANT**: Make sure to select the invoice in the payment wizard
5. Post the payment
6. Check logs immediately

### Step 2: Check Logs
Look for these log messages:
```
Payment <name> posted, found X related customer invoices for dropship processing
Invoice <name> payment_state after recompute: <state>
Invoice <name> is now <state> after payment <name>, triggering dropship processing
```

### Step 3: Use Debug Script
If POs still aren't created, use the debug script:

```bash
# Enter Odoo shell
sudo -u odoo /usr/bin/odoo-bin shell -d erp

# In the shell, run:
exec(open('/path/to/ox_sale_dropship_postpaid/debug_manual_payment.py').read())

# Then debug a specific payment:
debug_payment(payment_name='PAY/2024/0001')  # Replace with actual payment name

# Or test manual processing:
test_manual_processing(payment_name='PAY/2024/0001')
```

### Step 4: Common Issues

#### Issue: "No customer invoices found"
**Cause**: Payment wasn't linked to invoices during creation
**Solution**: 
- When manually registering payment, make sure to select invoices in the payment wizard
- Check if reconciliation happened: Look at payment's `invoice_ids` field
- The account_move write() method should catch this when reconciliation happens later

#### Issue: "Payment state is not paid/in_payment"
**Cause**: Reconciliation hasn't completed yet
**Solution**:
- Wait a few seconds and check again
- Manually reconcile payment with invoice if needed
- The write() method should catch this when payment_state changes

#### Issue: "No dropship route found"
**Cause**: Dropship route not configured
**Solution**:
- Verify dropship route exists: Inventory > Configuration > Routes
- Check route name contains "dropship" (case-insensitive)

#### Issue: "No sale orders found for invoice"
**Cause**: Invoice wasn't created from sale order
**Solution**:
- Verify invoice was created from sale order
- Check invoice lines have `sale_line_ids` populated

## Key Differences: Odoo.sh vs .deb Installation

Possible reasons why it works on Odoo.sh but not on .deb:

1. **Transaction timing**: .deb installation might have different transaction handling
2. **Module loading order**: Different addons path or module dependencies
3. **Database configuration**: Different PostgreSQL settings
4. **Workflow differences**: Manual payment registration might work differently

## Verification Checklist

After upgrading, verify:

- [ ] Module is upgraded: Check Apps > Installed Apps > "Dropship PO After Payment"
- [ ] Odoo server restarted
- [ ] Logs show processing messages when payment is posted
- [ ] Dropship route exists
- [ ] Test payment registration with invoice selected
- [ ] Check that POs are created after payment
- [ ] Check that POs are confirmed
- [ ] Check that vendor emails are sent

## Manual Fallback

If automatic processing still doesn't work, you can manually trigger it:

```python
# In Odoo shell
invoice = env['account.move'].browse(INVOICE_ID)
invoice.action_process_dropship_manually()
```

## Support

If issue persists:
1. Run debug script and share output
2. Check Odoo logs and share relevant messages
3. Verify module is correctly installed and upgraded
4. Compare Odoo versions between odoo.sh and client server
5. Check for conflicting modules


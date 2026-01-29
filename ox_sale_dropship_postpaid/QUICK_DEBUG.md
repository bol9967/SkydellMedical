# Quick Debug Guide - Server Issue

## Run Diagnostics on Your Server

### Option 1: Using Odoo Shell (Recommended)

```bash
# SSH into your server
ssh user@your-server

# Navigate to Odoo directory (usually /usr/lib/odoo or /opt/odoo)
cd /path/to/odoo

# Copy diagnose_server_issue.py to server (or create it there)

# Run diagnostics
./odoo-bin shell -d erp --no-http < diagnose_server_issue.py
```

### Option 2: Interactive Shell

```bash
# Start Odoo shell
./odoo-bin shell -d erp --no-http

# Then copy-paste the diagnostic code from diagnose_server_issue.py
# Or run individual functions:
```

```python
# In Odoo shell, run:
exec(open('diagnose_server_issue.py').read())

# Or test a specific payment:
test_payment_flow(payment_name='PAY/2024/0001')  # Replace with actual payment name
```

### Option 3: Test Specific Payment

```python
# In Odoo shell
payment = env['account.payment'].search([('name', '=', 'PAY/2024/0001')], limit=1)
print(f"Payment: {payment.name}")
print(f"Invoice IDs: {payment.invoice_ids.mapped('name')}")
print(f"Reconciled Invoice IDs: {payment.reconciled_invoice_ids.mapped('name')}")

# Check if action_post logic would find invoices
invoices = payment.invoice_ids | payment.reconciled_invoice_ids
if payment.move_id:
    for line in payment.move_id.line_ids:
        matched_lines = line.matched_debit_ids.mapped('debit_move_id') | \
                       line.matched_credit_ids.mapped('credit_move_id')
        for m_line in matched_lines:
            if m_line.move_id.move_type == 'out_invoice':
                invoices |= m_line.move_id

invoices = invoices.filtered(lambda inv: inv.move_type == 'out_invoice')
print(f"Found {len(invoices)} customer invoices")

# Test processing
for inv in invoices:
    inv.invalidate_recordset(['payment_state'])
    inv._compute_payment_state()
    print(f"Invoice {inv.name}: payment_state = {inv.payment_state}")
    if inv.payment_state in ('paid', 'in_payment'):
        inv._process_dropship_for_paid_invoice()
```

## What to Look For

### Issue 1: "No customer invoices found"
**Symptom**: Payment has no linked invoices
**Check**:
- Was invoice selected when creating payment?
- Is reconciliation happening?
- Check `payment.invoice_ids` and `payment.reconciled_invoice_ids`

### Issue 2: "Payment state not paid/in_payment"
**Symptom**: Invoices found but payment_state is not 'paid' or 'in_payment'
**Check**:
- Is reconciliation complete?
- Check invoice's `payment_state` field
- May need to wait for reconciliation or trigger it manually

### Issue 3: "Module methods not found"
**Symptom**: Methods don't exist
**Check**:
- Is module installed? `env['ir.module.module'].search([('name', '=', 'ox_sale_dropship_postpaid')])`
- Is module upgraded? Try: `odoo-bin -d erp -u ox_sale_dropship_postpaid --stop-after-init`
- Restart Odoo after upgrade

### Issue 4: "No dropship route found"
**Symptom**: Route not configured
**Check**:
- Inventory > Configuration > Routes
- Look for route with "dropship" in name

## Compare with Odoo.sh

To understand why it works on odoo.sh but not on your server:

1. **Check Odoo version**: `odoo-bin --version`
2. **Check installed modules**: Compare module list
3. **Check payment creation workflow**: How are payments created?
4. **Check reconciliation settings**: Are they different?

## Common Differences

### Odoo.sh vs .deb Installation

1. **Transaction handling**: Odoo.sh might have different transaction isolation
2. **Module loading**: Different addons path or loading order
3. **Database settings**: Different PostgreSQL configuration
4. **Workflow differences**: Payment registration might work differently

## Next Steps After Diagnostics

1. **If invoices not found**: Check payment creation process, ensure invoices are selected
2. **If payment_state wrong**: Check reconciliation, may need to trigger manually
3. **If module not loaded**: Reinstall/upgrade module, restart Odoo
4. **If processing fails**: Check error messages, review logs

## Get Help

Share the diagnostic output to identify the exact issue!


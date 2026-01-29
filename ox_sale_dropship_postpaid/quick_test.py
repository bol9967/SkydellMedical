# Quick inline test - copy-paste into Odoo shell
# odoo-bin shell -d erp --no-http

# Get most recent payment
payment = env['account.payment'].search([
    ('payment_type', '=', 'inbound'),
    ('state', '=', 'posted'),
], order='create_date desc', limit=1)

if not payment:
    print("No payment found!")
else:
    print(f"Payment: {payment.name}")
    print(f"Invoice IDs: {len(payment.invoice_ids)}")
    print(f"Reconciled Invoice IDs: {len(payment.reconciled_invoice_ids)}")
    
    # Check what action_post would see
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
    
    for inv in invoices:
        inv.invalidate_recordset(['payment_state'])
        inv._compute_payment_state()
        print(f"  Invoice {inv.name}: payment_state = {inv.payment_state}")
        
        if inv.payment_state in ('paid', 'in_payment'):
            print(f"    ✅ Would trigger processing")
        else:
            print(f"    ❌ Would NOT trigger (state: {inv.payment_state})")


# Check if account_payment.action_post() is being called and finding invoices
# Run this after manually registering a payment

# Find the payment for invoice INV/2025/12/1224
invoice = env['account.move'].search([('name', '=', 'INV/2025/12/1224')], limit=1)

if invoice:
    print(f"Invoice: {invoice.name}")
    print(f"Payment State: {invoice.payment_state}")
    
    # Find payments linked to this invoice
    payments = env['account.payment'].search([
        ('invoice_ids', 'in', [invoice.id])
    ]) | env['account.payment'].search([
        ('reconciled_invoice_ids', 'in', [invoice.id])
    ])
    
    print(f"\nPayments linked to invoice: {len(payments)}")
    for pay in payments:
        print(f"\n  Payment: {pay.name}")
        print(f"    State: {pay.state}")
        print(f"    Payment Type: {pay.payment_type}")
        print(f"    invoice_ids: {len(pay.invoice_ids)}")
        print(f"    reconciled_invoice_ids: {len(pay.reconciled_invoice_ids)}")
        
        # Check what action_post would see
        invoices_found = pay.invoice_ids | pay.reconciled_invoice_ids
        
        if pay.move_id:
            for line in pay.move_id.line_ids:
                matched_lines = line.matched_debit_ids.mapped('debit_move_id') | \
                               line.matched_credit_ids.mapped('credit_move_id')
                for m_line in matched_lines:
                    if m_line.move_id.move_type == 'out_invoice':
                        invoices_found |= m_line.move_id
        
        invoices_found = invoices_found.filtered(lambda inv: inv.move_type == 'out_invoice')
        print(f"    Would find {len(invoices_found)} customer invoices in action_post()")
        
        if len(invoices_found) == 0:
            print(f"    ❌ PROBLEM: action_post() would NOT find any invoices!")
            print(f"       This is why processing relies on account_move.write() instead")
        else:
            print(f"    ✅ action_post() would find invoices")
            
            # Check payment state
            for inv in invoices_found:
                inv.invalidate_recordset(['payment_state'])
                inv._compute_payment_state()
                print(f"      Invoice {inv.name}: payment_state = {inv.payment_state}")
                if inv.payment_state in ('paid', 'in_payment'):
                    print(f"        ✅ Would trigger processing in action_post()")
                else:
                    print(f"        ⚠️  Would NOT trigger (state: {inv.payment_state})")
else:
    print("Invoice not found")


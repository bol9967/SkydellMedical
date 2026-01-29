# Check Sale Order S00548
# Copy and paste this into your Odoo shell

so_name = 'S00548'
so = env['sale.order'].search([('name', '=', so_name)], limit=1)

if not so:
    print(f"❌ Sale Order {so_name} not found!")
else:
    print(f"\n{'='*80}")
    print(f"SALE ORDER: {so.name}")
    print(f"{'='*80}\n")
    
    print(f"Order Details:")
    print(f"  - ID: {so.id}")
    print(f"  - Name: {so.name}")
    print(f"  - State: {so.state}")
    print(f"  - Partner: {so.partner_id.name}")
    print(f"  - Amount Total: {so.amount_total}")
    
    # Check dropship route
    dropship_route = env['stock.route'].search([('name', 'ilike', 'dropship')], limit=1)
    if not dropship_route:
        print(f"\n❌ ERROR: No dropship route found!")
    else:
        print(f"\n✅ Dropship route found: {dropship_route.name} (ID: {dropship_route.id})")
    
    # Check order lines
    print(f"\nOrder Lines: {len(so.order_line)}")
    dropship_lines = env['sale.order.line']
    
    for line in so.order_line:
        is_dropship = False
        if dropship_route:
            if line.route_id and line.route_id.id == dropship_route.id:
                is_dropship = True
            elif dropship_route in line.product_id.route_ids:
                is_dropship = True
            elif line.product_id.categ_id and dropship_route in line.product_id.categ_id.route_ids:
                is_dropship = True
        
        route_info = f"Route: {line.route_id.name if line.route_id else 'None'}"
        if is_dropship:
            dropship_lines |= line
            print(f"  ✅ {line.product_id.name} - {route_info} - DROPSHIP")
        else:
            print(f"  - {line.product_id.name} - {route_info}")
    
    print(f"\nDropship Lines: {len(dropship_lines)}")
    
    # Check invoices
    print(f"\nInvoices: {len(so.invoice_ids)}")
    for inv in so.invoice_ids:
        print(f"  - {inv.name} | State: {inv.state} | Payment State: {inv.payment_state}")
        
        # Check payment transactions
        if hasattr(inv, 'transaction_ids'):
            txs = inv.transaction_ids.filtered(lambda t: t.state == 'done')
            print(f"    Done Transactions: {len(txs)}")
        
        # Check payments
        payments = env['account.payment'].search([
            ('invoice_ids', 'in', [inv.id])
        ]) | env['account.payment'].search([
            ('reconciled_invoice_ids', 'in', [inv.id])
        ])
        
        if payments:
            print(f"    Payments: {len(payments)}")
            for pay in payments:
                print(f"      - {pay.name} | State: {pay.state} | Amount: {pay.amount}")
        
        # Check if invoice is paid
        inv.invalidate_recordset(['payment_state'])
        inv._compute_payment_state()
        print(f"    Payment State (recomputed): {inv.payment_state}")
        
        if inv.payment_state in ('paid', 'in_payment'):
            print(f"    ✅ Invoice is PAID - should trigger dropship processing")
        else:
            print(f"    ⚠️  Invoice is NOT paid (state: {inv.payment_state})")
    
    # Check purchase orders
    if dropship_lines:
        print(f"\nPurchase Orders for Dropship Lines:")
        po_lines = env['purchase.order.line'].search([
            ('sale_line_id', 'in', dropship_lines.ids)
        ])
        pos = po_lines.mapped('order_id')
        print(f"  Found {len(pos)} purchase order(s)")
        for po in pos:
            print(f"    - {po.name} | State: {po.state} | Vendor: {po.partner_id.name}")
            print(f"      Processed Flag: {po.dropship_auto_email_processed}")
    else:
        print(f"\n⚠️  No dropship lines found - no POs should be created")
    
    # Check payment transactions on SO
    print(f"\nPayment Transactions on Sale Order:")
    if hasattr(so, 'transaction_ids'):
        txs = so.transaction_ids
        print(f"  Total: {len(txs)}")
        done_txs = txs.filtered(lambda t: t.state == 'done')
        print(f"  Done: {len(done_txs)}")
        for tx in done_txs:
            print(f"    - {tx.reference} | State: {tx.state} | Amount: {tx.amount}")
    
    # Summary
    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"✅ Dropship lines: {len(dropship_lines)}")
    print(f"✅ Invoices: {len(so.invoice_ids)}")
    
    paid_invoices = so.invoice_ids.filtered(
        lambda inv: inv.payment_state in ('paid', 'in_payment')
    )
    print(f"✅ Paid invoices: {len(paid_invoices)}")
    
    if dropship_lines:
        po_lines = env['purchase.order.line'].search([
            ('sale_line_id', 'in', dropship_lines.ids)
        ])
        pos = po_lines.mapped('order_id')
        print(f"✅ Purchase orders: {len(pos)}")
        
        if len(paid_invoices) > 0 and len(pos) == 0:
            print(f"\n❌ PROBLEM: Invoice is paid but NO purchase orders found!")
            print(f"   This indicates dropship processing didn't trigger.")
        elif len(paid_invoices) > 0 and len(pos) > 0:
            print(f"\n✅ Purchase orders exist - processing may have worked")
    
    print(f"\n{'='*80}\n")


# Check Sale Order S00556 - Why dropship PO not created when registering payment
so_name = 'S00556'
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
    
    if not dropship_lines:
        print("❌ PROBLEM: No dropship lines found! This is why PO is not created.")
        print("   Dropship POs are only created for dropship products.")
    
    # Check invoices
    print(f"\nInvoices: {len(so.invoice_ids)}")
    for inv in so.invoice_ids:
        print(f"\n  Invoice: {inv.name}")
        print(f"    State: {inv.state}")
        print(f"    Payment State: {inv.payment_state}")
        
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
                print(f"        Payment Type: {pay.payment_type}")
                print(f"        Invoice IDs: {len(pay.invoice_ids)}")
                print(f"        Reconciled Invoice IDs: {len(pay.reconciled_invoice_ids)}")
                
                # Check what action_post() would see
                invoices_found = pay.invoice_ids | pay.reconciled_invoice_ids
                if pay.move_id:
                    for line in pay.move_id.line_ids:
                        matched_lines = line.matched_debit_ids.mapped('debit_move_id') | \
                                       line.matched_credit_ids.mapped('credit_move_id')
                        for m_line in matched_lines:
                            if m_line.move_id.move_type == 'out_invoice':
                                invoices_found |= m_line.move_id
                
                invoices_found = invoices_found.filtered(lambda inv: inv.move_type == 'out_invoice')
                print(f"        Would find {len(invoices_found)} customer invoices in action_post()")
        else:
            print(f"    ⚠️  No payments found linked to this invoice")
        
        # Check if invoice is paid
        inv.invalidate_recordset(['payment_state'])
        inv._compute_payment_state()
        print(f"    Payment State (recomputed): {inv.payment_state}")
        
        if inv.payment_state in ('paid', 'in_payment'):
            print(f"    ✅ Invoice is PAID - should trigger dropship processing")
        else:
            print(f"    ⚠️  Invoice is NOT paid (state: {inv.payment_state})")
            print(f"       This is why dropship PO is not created!")
    
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
            print(f"      Created: {po.create_date}")
            print(f"      Processed Flag: {po.dropship_auto_email_processed}")
    else:
        print(f"\n⚠️  No dropship lines found - no POs should be created")
    
    # Summary and diagnosis
    print(f"\n{'='*80}")
    print(f"DIAGNOSIS")
    print(f"{'='*80}")
    
    paid_invoices = so.invoice_ids.filtered(
        lambda inv: inv.payment_state in ('paid', 'in_payment')
    )
    
    print(f"✅ Dropship lines: {len(dropship_lines)}")
    print(f"✅ Invoices: {len(so.invoice_ids)}")
    print(f"✅ Paid invoices: {len(paid_invoices)}")
    
    if dropship_lines:
        po_lines = env['purchase.order.line'].search([
            ('sale_line_id', 'in', dropship_lines.ids)
        ])
        pos = po_lines.mapped('order_id')
        print(f"✅ Purchase orders: {len(pos)}")
        
        if len(paid_invoices) > 0 and len(pos) == 0:
            print(f"\n❌ PROBLEM IDENTIFIED:")
            print(f"   Invoice is paid but NO purchase orders found!")
            print(f"   Possible causes:")
            print(f"   1. Payment was registered but action_post() didn't trigger")
            print(f"   2. action_post() didn't find invoices")
            print(f"   3. account_move.write() didn't trigger")
            print(f"   4. Processing failed silently")
            print(f"\n   Let's test manual processing...")
            
            # Try manual processing
            for inv in paid_invoices:
                print(f"\n   Attempting manual processing for {inv.name}...")
                try:
                    inv._process_dropship_for_paid_invoice()
                    print(f"   ✅ Manual processing triggered")
                    
                    # Check if PO was created
                    env.invalidate_all()
                    po_lines_after = env['purchase.order.line'].search([
                        ('sale_line_id', 'in', dropship_lines.ids)
                    ])
                    pos_after = po_lines_after.mapped('order_id')
                    print(f"   Purchase orders after: {len(pos_after)}")
                    for po in pos_after:
                        print(f"     - {po.name} | State: {po.state}")
                except Exception as e:
                    print(f"   ❌ ERROR: {str(e)}")
                    import traceback
                    traceback.print_exc()
        elif len(paid_invoices) == 0:
            print(f"\n❌ PROBLEM: Invoice is NOT paid!")
            print(f"   Payment must be registered and posted for dropship PO to be created.")
        elif len(pos) > 0:
            print(f"\n✅ Purchase orders exist - processing worked!")
    else:
        print(f"\n❌ PROBLEM: No dropship lines found!")
        print(f"   Dropship POs are only created for products with dropship route.")
    
    print(f"\n{'='*80}\n")


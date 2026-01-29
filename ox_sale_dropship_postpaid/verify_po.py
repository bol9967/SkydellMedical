# Verify Purchase Order P00308
# Check if it exists and is correctly linked

po_name = 'P00308'
po = env['purchase.order'].search([('name', '=', po_name)], limit=1)

if not po:
    print(f"❌ Purchase Order {po_name} NOT FOUND!")
else:
    print(f"\n{'='*80}")
    print(f"PURCHASE ORDER: {po.name}")
    print(f"{'='*80}\n")
    
    print(f"PO Details:")
    print(f"  - ID: {po.id}")
    print(f"  - Name: {po.name}")
    print(f"  - State: {po.state}")
    print(f"  - Vendor: {po.partner_id.name}")
    print(f"  - Date Order: {po.date_order}")
    print(f"  - Create Date: {po.create_date}")
    print(f"  - Dropship Auto Email Processed: {po.dropship_auto_email_processed}")
    
    # Check PO lines
    print(f"\nPO Lines: {len(po.order_line)}")
    for line in po.order_line:
        print(f"  - {line.product_id.name}")
        print(f"    Quantity: {line.product_qty}")
        print(f"    Price: {line.price_unit}")
        print(f"    Sale Line ID: {line.sale_line_id.id if line.sale_line_id else 'None'}")
        print(f"    Sale Line: {line.sale_line_id.name if line.sale_line_id else 'None'}")
        
        # Check if linked to sale order
        if line.sale_line_id:
            so = line.sale_line_id.order_id
            print(f"    Sale Order: {so.name}")
            print(f"    SO State: {so.state}")
            
            # Check if it's a dropship line
            dropship_route = env['stock.route'].search([('name', 'ilike', 'dropship')], limit=1)
            if dropship_route:
                is_dropship = (
                    (line.sale_line_id.route_id and line.sale_line_id.route_id.id == dropship_route.id)
                    or (dropship_route in line.sale_line_id.product_id.route_ids)
                    or (line.sale_line_id.product_id.categ_id and dropship_route in line.sale_line_id.product_id.categ_id.route_ids)
                )
                print(f"    Is Dropship: {is_dropship}")
    
    # Check related sale orders
    sale_lines = po.order_line.mapped('sale_line_id')
    sale_orders = sale_lines.mapped('order_id')
    print(f"\nRelated Sale Orders: {len(sale_orders)}")
    for so in sale_orders:
        print(f"  - {so.name} | State: {so.state}")
        
        # Check invoices
        invoices = so.invoice_ids
        print(f"    Invoices: {len(invoices)}")
        for inv in invoices:
            inv.invalidate_recordset(['payment_state'])
            inv._compute_payment_state()
            print(f"      - {inv.name} | State: {inv.state} | Payment State: {inv.payment_state}")
            
            # Check payments
            payments = env['account.payment'].search([
                ('invoice_ids', 'in', [inv.id])
            ]) | env['account.payment'].search([
                ('reconciled_invoice_ids', 'in', [inv.id])
            ])
            if payments:
                print(f"        Payments: {len(payments)}")
                for pay in payments:
                    print(f"          - {pay.name} | State: {pay.state}")
    
    # Check if PO was created correctly
    print(f"\n{'='*80}")
    print(f"VERIFICATION SUMMARY")
    print(f"{'='*80}")
    
    issues = []
    
    # Check 1: PO state
    if po.state not in ('purchase', 'done'):
        issues.append(f"⚠️  PO state is '{po.state}' (expected 'purchase' or 'done')")
    else:
        print(f"✅ PO state: {po.state}")
    
    # Check 2: Has sale line links
    if not sale_lines:
        issues.append("❌ PO lines are NOT linked to sale order lines!")
    else:
        print(f"✅ PO lines linked to {len(sale_lines)} sale order line(s)")
    
    # Check 3: Dropship route
    dropship_route = env['stock.route'].search([('name', 'ilike', 'dropship')], limit=1)
    if dropship_route:
        dropship_lines = sale_lines.filtered(
            lambda l: (
                (l.route_id and l.route_id.id == dropship_route.id)
                or (dropship_route in l.product_id.route_ids)
                or (l.product_id.categ_id and dropship_route in l.product_id.categ_id.route_ids)
            )
        )
        if not dropship_lines:
            issues.append("⚠️  Linked sale lines are NOT dropship lines")
        else:
            print(f"✅ Linked to {len(dropship_lines)} dropship line(s)")
    else:
        issues.append("❌ Dropship route not found")
    
    # Check 4: Invoice payment status
    all_invoices = sale_orders.mapped('invoice_ids')
    if all_invoices:
        paid_invoices = all_invoices.filtered(
            lambda inv: inv.payment_state in ('paid', 'in_payment')
        )
        if not paid_invoices:
            issues.append("⚠️  No paid invoices found (PO might have been created before payment)")
        else:
            print(f"✅ Found {len(paid_invoices)} paid invoice(s)")
    else:
        issues.append("⚠️  No invoices found for related sale orders")
    
    # Check 5: Processed flag
    if not po.dropship_auto_email_processed:
        issues.append("⚠️  PO not marked as processed (email might not have been sent)")
    else:
        print(f"✅ PO marked as processed (email sent)")
    
    # Check 6: PO creation timing
    if sale_orders:
        latest_invoice = max(sale_orders.mapped('invoice_ids'), key=lambda inv: inv.create_date, default=None)
        if latest_invoice:
            if po.create_date < latest_invoice.create_date:
                issues.append("⚠️  PO created before invoice (unusual)")
            else:
                print(f"✅ PO created after invoice (expected)")
    
    if issues:
        print(f"\n⚠️  ISSUES FOUND:")
        for issue in issues:
            print(f"  {issue}")
    else:
        print(f"\n✅ ALL CHECKS PASSED - PO looks correct!")
    
    print(f"\n{'='*80}\n")


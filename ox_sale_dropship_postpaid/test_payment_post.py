# Test what happens when payment is posted
# This will simulate action_post() being called

payment = env['account.payment'].search([('name', '=', 'PBNK1/2025/00021')], limit=1)

if not payment:
    print("Payment not found!")
else:
    print(f"Payment: {payment.name}")
    print(f"Current State: {payment.state}")
    
    # Check if payment is already posted
    if payment.state == 'posted':
        print("Payment is already posted. Checking what action_post() would do...")
        
        # Manually call the logic from action_post()
        if payment.payment_type == 'inbound':
            env.flush_all()
            
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
            
            for invoice in invoices:
                invoice.invalidate_recordset(['payment_state'])
                invoice._compute_payment_state()
                print(f"  Invoice {invoice.name}: payment_state = {invoice.payment_state}")
                
                if invoice.payment_state in ('paid', 'in_payment'):
                    print(f"    ✅ Would trigger processing")
                else:
                    print(f"    ❌ Would NOT trigger (state: {invoice.payment_state})")
    else:
        print(f"Payment is NOT posted (state: {payment.state})")
        print("This is why action_post() hasn't been called yet!")
        print("\nTo test, you need to:")
        print("1. Post the payment in Odoo UI")
        print("2. Check logs for 'ox_sale_dropship_postpaid: action_post() called'")
        print("3. Or manually trigger action_post() here (but this might have side effects)")
        
        # Check if we can see what would happen
        print("\nChecking what invoices would be found when payment is posted...")
        invoices = payment.invoice_ids | payment.reconciled_invoice_ids
        
        if payment.move_id:
            for line in payment.move_id.line_ids:
                matched_lines = line.matched_debit_ids.mapped('debit_move_id') | \
                               line.matched_credit_ids.mapped('credit_move_id')
                for m_line in matched_lines:
                    if m_line.move_id.move_type == 'out_invoice':
                        invoices |= m_line.move_id
        
        invoices = invoices.filtered(lambda inv: inv.move_type == 'out_invoice')
        print(f"Would find {len(invoices)} customer invoices")
        
        for invoice in invoices:
            invoice.invalidate_recordset(['payment_state'])
            invoice._compute_payment_state()
            print(f"  Invoice {invoice.name}: payment_state = {invoice.payment_state}")
            
            # Check if invoice has dropship lines
            sale_orders = invoice.invoice_line_ids.sale_line_ids.mapped('order_id')
            if sale_orders:
                dropship_route = env['stock.route'].search([('name', 'ilike', 'dropship')], limit=1)
                if dropship_route:
                    for so in sale_orders:
                        dropship_lines = so.order_line.filtered(
                            lambda l: (
                                (l.route_id and l.route_id.id == dropship_route.id)
                                or (dropship_route in l.product_id.route_ids)
                                or (l.product_id.categ_id and dropship_route in l.product_id.categ_id.route_ids)
                            )
                        )
                        if dropship_lines:
                            print(f"    Sale Order {so.name}: {len(dropship_lines)} dropship lines")
                            
                            # Check if POs exist
                            po_lines = env['purchase.order.line'].search([
                                ('sale_line_id', 'in', dropship_lines.ids)
                            ])
                            pos = po_lines.mapped('order_id')
                            print(f"    Existing POs: {len(pos)}")
                            for po in pos:
                                print(f"      - {po.name} | State: {po.state}")


# Test what happens when payment is actually posted
# This simulates the real scenario

payment = env['account.payment'].search([('name', '=', 'PBNK1/2025/00021')], limit=1)

if not payment:
    print("Payment not found!")
else:
    print(f"Payment: {payment.name}")
    print(f"Current State: {payment.state}")
    
    if payment.state == 'posted':
        print("\n✅ Payment is already posted")
        print("Checking if action_post() was called and what it did...")
        
        # Check if PO exists
        invoice = payment.invoice_ids[0] if payment.invoice_ids else None
        if invoice:
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
                            po_lines = env['purchase.order.line'].search([
                                ('sale_line_id', 'in', dropship_lines.ids)
                            ])
                            pos = po_lines.mapped('order_id')
                            print(f"\nPurchase Orders: {len(pos)}")
                            for po in pos:
                                print(f"  - {po.name} | State: {po.state} | Created: {po.create_date}")
                                print(f"    Processed: {po.dropship_auto_email_processed}")
    else:
        print(f"\n⚠️  Payment is NOT posted (state: {payment.state})")
        print("\nTo test the real flow:")
        print("1. Post the payment in Odoo UI")
        print("2. Immediately check logs for:")
        print("   - 'ox_sale_dropship_postpaid: action_post() called'")
        print("   - 'Payment X posted, found X related customer invoices'")
        print("   - 'Invoice X is now X after payment X, triggering dropship processing'")
        print("3. Check if PO is created")
        print("\nNOTE: The PO might already exist if account_move.write() created it earlier")
        print("      when the invoice payment_state changed to 'in_payment'")


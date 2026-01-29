#!/usr/bin/env python3
"""
Server Diagnostic Script for Manual Payment Issue
Run: odoo-bin shell -d erp --no-http < diagnose_server_issue.py
Or copy-paste into Odoo shell
"""

import logging
_logger = logging.getLogger(__name__)

def diagnose_module():
    """Check if module is properly installed and loaded"""
    print("\n" + "="*80)
    print("MODULE DIAGNOSTICS")
    print("="*80)
    
    # Check if module is installed
    module = env['ir.module.module'].search([
        ('name', '=', 'ox_sale_dropship_postpaid'),
        ('state', '=', 'installed')
    ])
    
    if not module:
        print("❌ ERROR: Module 'ox_sale_dropship_postpaid' is NOT installed!")
        return False
    else:
        print(f"✅ Module is installed (state: {module.state})")
    
    # Check if models are loaded
    models_to_check = [
        'account.payment',
        'account.move',
        'sale.order.line',
        'purchase.order',
    ]
    
    for model_name in models_to_check:
        if model_name in env:
            print(f"✅ Model '{model_name}' is available")
        else:
            print(f"❌ Model '{model_name}' is NOT available!")
            return False
    
    # Check if our methods exist
    payment_model = env['account.payment']
    if hasattr(payment_model, 'action_post'):
        print("✅ account.payment.action_post() method exists")
    else:
        print("❌ account.payment.action_post() method NOT found!")
        return False
    
    move_model = env['account.move']
    if hasattr(move_model, '_process_dropship_for_paid_invoice'):
        print("✅ account.move._process_dropship_for_paid_invoice() method exists")
    else:
        print("❌ account.move._process_dropship_for_paid_invoice() method NOT found!")
        return False
    
    # Check dropship route
    dropship_route = env['stock.route'].search([('name', 'ilike', 'dropship')], limit=1)
    if dropship_route:
        print(f"✅ Dropship route found: {dropship_route.name} (ID: {dropship_route.id})")
    else:
        print("⚠️  WARNING: No dropship route found!")
    
    return True


def test_payment_flow(payment_id=None, payment_name=None):
    """Test a specific payment to see what happens"""
    print("\n" + "="*80)
    print("PAYMENT FLOW TEST")
    print("="*80)
    
    # Find payment
    if payment_id:
        payment = env['account.payment'].browse(payment_id)
    elif payment_name:
        payment = env['account.payment'].search([('name', '=', payment_name)], limit=1)
    else:
        # Get most recent inbound payment
        payment = env['account.payment'].search([
            ('payment_type', '=', 'inbound'),
            ('state', '=', 'posted'),
        ], order='create_date desc', limit=1)
    
    if not payment:
        print("❌ No payment found!")
        return
    
    print(f"\nTesting Payment: {payment.name} (ID: {payment.id})")
    print(f"  State: {payment.state}")
    print(f"  Payment Type: {payment.payment_type}")
    print(f"  Partner: {payment.partner_id.name if payment.partner_id else 'None'}")
    print(f"  Amount: {payment.amount}")
    print(f"  Move ID: {payment.move_id.name if payment.move_id else 'None'}")
    
    # Check invoice links
    print(f"\nInvoice Links:")
    print(f"  invoice_ids: {len(payment.invoice_ids)}")
    for inv in payment.invoice_ids:
        print(f"    - {inv.name} | Type: {inv.move_type} | State: {inv.state} | Payment State: {inv.payment_state}")
    
    print(f"  reconciled_invoice_ids: {len(payment.reconciled_invoice_ids)}")
    for inv in payment.reconciled_invoice_ids:
        print(f"    - {inv.name} | Type: {inv.move_type} | State: {inv.state} | Payment State: {inv.payment_state}")
    
    # Check move lines
    if payment.move_id:
        print(f"\nPayment Move Lines:")
        for line in payment.move_id.line_ids:
            print(f"  - Account: {line.account_id.name} | Debit: {line.debit} | Credit: {line.credit} | Reconciled: {line.reconciled}")
            
            # Check matched lines
            matched_debit = line.matched_debit_ids.mapped('debit_move_id')
            matched_credit = line.matched_credit_ids.mapped('credit_move_id')
            matched_lines = matched_debit | matched_credit
            
            if matched_lines:
                print(f"    Matched with {len(matched_lines)} lines:")
                for m_line in matched_lines:
                    m_move = m_line.move_id
                    print(f"      * {m_move.name} ({m_move.move_type})")
    
    # Get all customer invoices
    all_invoices = payment.invoice_ids | payment.reconciled_invoice_ids
    if payment.move_id:
        for line in payment.move_id.line_ids:
            matched_lines = line.matched_debit_ids.mapped('debit_move_id') | \
                          line.matched_credit_ids.mapped('credit_move_id')
            for m_line in matched_lines:
                if m_line.move_id.move_type == 'out_invoice':
                    all_invoices |= m_line.move_id
    
    all_invoices = all_invoices.filtered(lambda inv: inv.move_type == 'out_invoice')
    
    print(f"\nFound {len(all_invoices)} customer invoice(s)")
    
    if not all_invoices:
        print("❌ NO CUSTOMER INVOICES FOUND - This is likely the problem!")
        print("\nPossible reasons:")
        print("  1. Payment was created without selecting invoices")
        print("  2. Reconciliation hasn't happened yet")
        print("  3. Payment is linked to vendor bills instead")
        return
    
    # Test each invoice
    for invoice in all_invoices:
        print(f"\n{'='*60}")
        print(f"Invoice: {invoice.name}")
        print(f"{'='*60}")
        
        # Check payment state
        print(f"Payment State (before recompute): {invoice.payment_state}")
        invoice.invalidate_recordset(['payment_state'])
        invoice._compute_payment_state()
        invoice.flush_recordset(['payment_state'])
        env.invalidate_all()
        print(f"Payment State (after recompute): {invoice.payment_state}")
        
        if invoice.payment_state not in ('paid', 'in_payment'):
            print(f"⚠️  Invoice is NOT paid/in_payment (state: {invoice.payment_state})")
            print("   This might be why dropship POs aren't created")
            continue
        
        # Check sale orders
        sale_orders = invoice.invoice_line_ids.sale_line_ids.mapped('order_id')
        print(f"Sale Orders: {len(sale_orders)}")
        
        if not sale_orders:
            print("❌ No sale orders found for this invoice!")
            continue
        
        # Check dropship lines
        dropship_route = env['stock.route'].search([('name', 'ilike', 'dropship')], limit=1)
        if not dropship_route:
            print("❌ No dropship route found!")
            continue
        
        all_dropship_lines = env['sale.order.line']
        for so in sale_orders:
            dropship_lines = so.order_line.filtered(
                lambda l: (
                    (l.route_id and l.route_id.id == dropship_route.id)
                    or (dropship_route in l.product_id.route_ids)
                    or (l.product_id.categ_id and dropship_route in l.product_id.categ_id.route_ids)
                )
            )
            if dropship_lines:
                all_dropship_lines |= dropship_lines
                print(f"  Order {so.name}: {len(dropship_lines)} dropship lines")
        
        if not all_dropship_lines:
            print("❌ No dropship lines found!")
            continue
        
        print(f"✅ Found {len(all_dropship_lines)} dropship lines total")
        
        # Check for existing POs
        po_lines = env['purchase.order.line'].search([
            ('sale_line_id', 'in', all_dropship_lines.ids)
        ])
        pos = po_lines.mapped('order_id')
        print(f"Existing Purchase Orders: {len(pos)}")
        for po in pos:
            print(f"  - {po.name} | State: {po.state} | Processed: {po.dropship_auto_email_processed}")
        
        # Try to manually trigger processing
        print(f"\n🔧 Attempting to manually trigger dropship processing...")
        try:
            invoice._process_dropship_for_paid_invoice()
            print("✅ Processing triggered successfully")
            
            # Check if POs were created
            env.invalidate_all()
            po_lines_after = env['purchase.order.line'].search([
                ('sale_line_id', 'in', all_dropship_lines.ids)
            ])
            pos_after = po_lines_after.mapped('order_id')
            print(f"Purchase Orders after processing: {len(pos_after)}")
            for po in pos_after:
                print(f"  - {po.name} | State: {po.state} | Processed: {po.dropship_auto_email_processed}")
        except Exception as e:
            print(f"❌ ERROR during processing: {str(e)}")
            import traceback
            traceback.print_exc()


def simulate_action_post(payment_id=None):
    """Simulate what happens when action_post is called"""
    print("\n" + "="*80)
    print("SIMULATING action_post() CALL")
    print("="*80)
    
    if payment_id:
        payment = env['account.payment'].browse(payment_id)
    else:
        payment = env['account.payment'].search([
            ('payment_type', '=', 'inbound'),
            ('state', '=', 'posted'),
        ], order='create_date desc', limit=1)
    
    if not payment:
        print("❌ No payment found!")
        return
    
    print(f"Simulating action_post for payment: {payment.name}")
    
    # Manually call the logic from action_post
    if payment.payment_type != 'inbound':
        print("⚠️  Payment is not inbound, skipping")
        return
    
    env.flush_all()
    
    # Get invoices (same logic as in action_post)
    invoices = payment.invoice_ids | payment.reconciled_invoice_ids
    
    if not invoices and payment.move_id:
        payment_move_lines = payment.move_id.line_ids
        for line in payment_move_lines:
            matched_lines = line.matched_debit_ids.mapped('debit_move_id') | \
                          line.matched_credit_ids.mapped('credit_move_id')
            for matched_line in matched_lines:
                matched_move = matched_line.move_id
                if matched_move.move_type == 'out_invoice':
                    invoices |= matched_move
    
    invoices = invoices.filtered(lambda inv: inv.move_type == 'out_invoice')
    
    print(f"Found {len(invoices)} customer invoice(s)")
    
    if not invoices:
        print("❌ No invoices found - this is what action_post() would see")
        return
    
    for invoice in invoices:
        print(f"\nProcessing invoice: {invoice.name}")
        invoice.invalidate_recordset(['payment_state'])
        invoice._compute_payment_state()
        invoice.flush_recordset(['payment_state'])
        env.invalidate_all()
        
        print(f"  Payment State: {invoice.payment_state}")
        
        if invoice.payment_state in ('paid', 'in_payment'):
            print("  ✅ Invoice is paid/in_payment - would trigger processing")
            try:
                invoice._process_dropship_for_paid_invoice()
                print("  ✅ Processing completed")
            except Exception as e:
                print(f"  ❌ Error: {str(e)}")
        else:
            print(f"  ⚠️  Invoice is NOT paid/in_payment - would NOT trigger processing")


def check_logs():
    """Check recent logs for the module"""
    print("\n" + "="*80)
    print("RECENT LOG ENTRIES")
    print("="*80)
    print("(Note: This requires log access. Check Odoo log file manually)")
    print("Look for messages containing:")
    print("  - 'Payment.*posted.*found.*customer invoices'")
    print("  - 'Invoice.*payment_state after recompute'")
    print("  - 'Processing paid invoice'")
    print("  - 'No customer invoices found'")


# Main execution
if __name__ == '__main__' or 'env' in globals():
    print("\n" + "="*80)
    print("OX_SALE_DROPSHIP_POSTPAID - SERVER DIAGNOSTICS")
    print("="*80)
    
    # Step 1: Check module
    if not diagnose_module():
        print("\n❌ Module diagnostics failed. Please check module installation.")
        exit(1)
    
    # Step 2: Test payment flow
    print("\n" + "="*80)
    print("STEP 1: Testing recent payment")
    print("="*80)
    test_payment_flow()
    
    # Step 3: Simulate action_post
    print("\n" + "="*80)
    print("STEP 2: Simulating action_post()")
    print("="*80)
    simulate_action_post()
    
    # Step 4: Check logs
    check_logs()
    
    print("\n" + "="*80)
    print("DIAGNOSTICS COMPLETE")
    print("="*80)
    print("\nNext steps:")
    print("1. Review the output above")
    print("2. If 'No customer invoices found' - check payment creation process")
    print("3. If invoices found but payment_state not paid - check reconciliation")
    print("4. If processing fails - check error messages above")
    print("5. Check Odoo logs for detailed error messages")
    print("\n")


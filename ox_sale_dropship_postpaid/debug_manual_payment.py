#!/usr/bin/env python3
"""
Debug script for manual payment registration issue.
Run this in Odoo shell: odoo-bin shell -d erp
Then copy-paste the code below.
"""

def debug_payment(payment_name=None, payment_id=None):
    """
    Debug a specific payment to see why dropship POs aren't being created.
    
    Usage:
        # By payment name
        debug_payment(payment_name='PAY/2024/0001')
        
        # By payment ID
        debug_payment(payment_id=123)
    """
    import logging
    _logger = logging.getLogger(__name__)
    
    # Find the payment
    if payment_id:
        payment = env['account.payment'].browse(payment_id)
    elif payment_name:
        payment = env['account.payment'].search([('name', '=', payment_name)], limit=1)
    else:
        # Get the most recent payment
        payment = env['account.payment'].search([
            ('payment_type', '=', 'inbound'),
            ('state', '=', 'posted'),
        ], order='create_date desc', limit=1)
    
    if not payment:
        print("No payment found!")
        return
    
    print(f"\n{'='*80}")
    print(f"DEBUGGING PAYMENT: {payment.name}")
    print(f"{'='*80}\n")
    
    print(f"Payment Details:")
    print(f"  - ID: {payment.id}")
    print(f"  - Name: {payment.name}")
    print(f"  - State: {payment.state}")
    print(f"  - Payment Type: {payment.payment_type}")
    print(f"  - Partner: {payment.partner_id.name if payment.partner_id else 'None'}")
    print(f"  - Amount: {payment.amount}")
    print(f"  - Date: {payment.date}")
    print(f"  - Move ID: {payment.move_id.name if payment.move_id else 'None'}")
    print(f"  - Destination Account: {payment.destination_account_id.name if payment.destination_account_id else 'None'}")
    
    print(f"\nInvoice Links:")
    print(f"  - invoice_ids (explicitly linked): {len(payment.invoice_ids)}")
    for inv in payment.invoice_ids:
        print(f"    * {inv.name} - {inv.payment_state} - Amount: {inv.amount_total}")
    
    print(f"  - reconciled_invoice_ids: {len(payment.reconciled_invoice_ids)}")
    for inv in payment.reconciled_invoice_ids:
        print(f"    * {inv.name} - {inv.payment_state} - Amount: {inv.amount_total}")
    
    # Check move lines
    if payment.move_id:
        print(f"\nPayment Move Lines:")
        for line in payment.move_id.line_ids:
            print(f"  - {line.account_id.name} | Debit: {line.debit} | Credit: {line.credit} | Reconciled: {line.reconciled}")
            
            # Check matched lines
            matched_debit = line.matched_debit_ids.mapped('debit_move_id')
            matched_credit = line.matched_credit_ids.mapped('credit_move_id')
            matched_lines = matched_debit | matched_credit
            
            if matched_lines:
                print(f"    Matched with {len(matched_lines)} lines:")
                for m_line in matched_lines:
                    m_move = m_line.move_id
                    print(f"      * {m_move.name} ({m_move.move_type}) - Line: {m_line.account_id.name}")
                    if m_move.move_type == 'out_invoice':
                        print(f"        >>> FOUND CUSTOMER INVOICE: {m_move.name}")
    
    # Check if invoices have dropship lines
    all_invoices = payment.invoice_ids | payment.reconciled_invoice_ids
    if payment.move_id:
        for line in payment.move_id.line_ids:
            matched_lines = line.matched_debit_ids.mapped('debit_move_id') | \
                          line.matched_credit_ids.mapped('credit_move_id')
            for m_line in matched_lines:
                if m_line.move_id.move_type == 'out_invoice':
                    all_invoices |= m_line.move_id
    
    all_invoices = all_invoices.filtered(lambda inv: inv.move_type == 'out_invoice')
    
    if all_invoices:
        print(f"\nFound {len(all_invoices)} customer invoice(s). Checking for dropship lines...")
        
        dropship_route = env['stock.route'].search([('name', 'ilike', 'dropship')], limit=1)
        if not dropship_route:
            print("  ERROR: No dropship route found!")
        else:
            print(f"  Dropship route: {dropship_route.name}")
            
            for invoice in all_invoices:
                print(f"\n  Invoice: {invoice.name}")
                print(f"    Payment State: {invoice.payment_state}")
                
                # Get sale orders
                sale_orders = invoice.invoice_line_ids.sale_line_ids.mapped('order_id')
                print(f"    Sale Orders: {len(sale_orders)}")
                
                if sale_orders:
                    for so in sale_orders:
                        print(f"      - {so.name}")
                        dropship_lines = so.order_line.filtered(
                            lambda l: (
                                (l.route_id and l.route_id.id == dropship_route.id)
                                or (dropship_route in l.product_id.route_ids)
                                or (l.product_id.categ_id and dropship_route in l.product_id.categ_id.route_ids)
                            )
                        )
                        print(f"        Dropship lines: {len(dropship_lines)}")
                        
                        # Check for existing POs
                        if dropship_lines:
                            po_lines = env['purchase.order.line'].search([
                                ('sale_line_id', 'in', dropship_lines.ids)
                            ])
                            pos = po_lines.mapped('order_id')
                            print(f"        Existing POs: {len(pos)}")
                            for po in pos:
                                print(f"          - {po.name} ({po.state})")
                else:
                    print(f"    No sale orders found for this invoice!")
    else:
        print(f"\n  NO CUSTOMER INVOICES FOUND!")
        print(f"  This is the problem - payment is not linked to any customer invoices.")
        print(f"  Possible causes:")
        print(f"    1. Payment was created without selecting invoices")
        print(f"    2. Reconciliation hasn't happened yet")
        print(f"    3. Payment is linked to vendor bills instead of customer invoices")
    
    print(f"\n{'='*80}\n")
    
    return payment


def test_manual_processing(payment_name=None, payment_id=None):
    """
    Test manual processing of dropship POs for a payment.
    """
    payment = debug_payment(payment_name=payment_name, payment_id=payment_id)
    
    if not payment:
        return
    
    # Get all invoices
    all_invoices = payment.invoice_ids | payment.reconciled_invoice_ids
    if payment.move_id:
        for line in payment.move_id.line_ids:
            matched_lines = line.matched_debit_ids.mapped('debit_move_id') | \
                          line.matched_credit_ids.mapped('credit_move_id')
            for m_line in matched_lines:
                if m_line.move_id.move_type == 'out_invoice':
                    all_invoices |= m_line.move_id
    
    all_invoices = all_invoices.filtered(lambda inv: inv.move_type == 'out_invoice')
    
    if not all_invoices:
        print("No customer invoices found. Cannot process.")
        return
    
    print(f"\nAttempting to manually process {len(all_invoices)} invoice(s)...")
    
    for invoice in all_invoices:
        print(f"\nProcessing invoice: {invoice.name}")
        
        # Force recompute payment_state
        invoice.invalidate_recordset(['payment_state'])
        invoice._compute_payment_state()
        invoice.flush_recordset(['payment_state'])
        env.invalidate_all()
        
        print(f"  Payment State: {invoice.payment_state}")
        
        if invoice.payment_state in ('paid', 'in_payment'):
            try:
                invoice._process_dropship_for_paid_invoice()
                print(f"  SUCCESS: Processing triggered for {invoice.name}")
            except Exception as e:
                print(f"  ERROR: {str(e)}")
                import traceback
                traceback.print_exc()
        else:
            print(f"  SKIPPED: Invoice is not paid (payment_state: {invoice.payment_state})")


# Example usage:
# debug_payment(payment_name='PAY/2024/0001')
# test_manual_processing(payment_name='PAY/2024/0001')


# Copy and paste this into your Odoo shell to run the debug

# First, let's find a recent payment
payment = env['account.payment'].search([
    ('payment_type', '=', 'inbound'),
    ('state', '=', 'posted'),
], order='create_date desc', limit=1)

if payment:
    print(f"\nFound payment: {payment.name}")
    print(f"Now running debug_payment()...\n")
    debug_payment(payment_id=payment.id)
else:
    print("No payment found. Please create a test payment first.")

# Or if you know the payment name, use:
# debug_payment(payment_name='PAY/2024/0001')


# Part of Odoo. See LICENSE file for full copyright and licensing details.

from . import sale_order
from . import payment_provider
from . import account_move

# Conditionally import compatibility layer for ox_peptide_shipping
# This ensures payment fee lines are excluded from peptide detection logic
# The compatibility layer will only work if ox_peptide_shipping is installed
# Note: ox_peptide_shipping has been updated to check for is_payment_fee directly,
# but this compatibility layer provides additional safety
try:
    from . import ox_peptide_shipping_compat
except ImportError:
    # ox_peptide_shipping module not installed, skip compatibility layer
    pass


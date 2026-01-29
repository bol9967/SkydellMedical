{
    "name": "Edit Sequence No.",

    'version': "18.0",

    'category': "other",

    "summary": "Allows users to edit sequence numbers for sales, purchase, warehouse, and accounting orders.",
    "description": """
        This app enables users to edit sequence numbers for various records including sales orders, purchase orders, warehouse operations, and accounting invoices.
        Users with appropriate permissions can change the sequence number for individual records, but will be prevented from using duplicate sequence numbers through validation.

        Features:
        - Edit sequence numbers for sales orders, purchase orders, warehouse operations, and accounting invoices.
        - User-specific access control to edit sequence numbers.
        - Validation error prevents duplicate sequence numbers from being saved.
    """,

    'author': "M Jamshaid",
    'website': 'https://www.outsetx.com/',
    "depends": ["sale_management", "purchase", "stock", "account"],

    "data": ["security/security.xml",
             'views/sale_order_view.xml',
             'views/purchase_order_view.xml',
             'views/account_move_view.xml',
             'views/stock_picking_view.xml'],
    'images': ['static/description/banner.gif'],
    'license': "OPL-1",
    'installable': True,
    'application': True,
    'auto_install': False,
}

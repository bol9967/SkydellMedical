from odoo import models, fields

class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    partner_npi = fields.Char(
        string="NPI# ",
        related="partner_id.npi_number",
        store=False,
        readonly=True,
    )

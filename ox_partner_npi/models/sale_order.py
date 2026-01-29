from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = "sale.order"

    partner_npi = fields.Char(
        string="NPI#",
        related="partner_id.npi_number",
        store=False,
        readonly=True,
    )
    invoice_npi = fields.Char(
        string="Invoice NPI",
        related="partner_invoice_id.npi_number",
        store=False,
        readonly=True,
    )
    shipping_npi = fields.Char(
        string="Shipping NPI",
        related="partner_shipping_id.npi_number",
        store=False,
        readonly=True,
    )

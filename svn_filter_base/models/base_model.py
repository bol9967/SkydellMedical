# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

from ast import literal_eval

from odoo import models
from odoo.osv.expression import normalize_domain, AND


class Base(models.AbstractModel):
    _inherit = 'base'

    def uweb_filter_x2(self, domains):
        return self.filtered_domain(AND(normalize_domain(literal_eval(d)) for d in domains)).ids

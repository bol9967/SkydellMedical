# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

from odoo import models
from odoo.http import request


class Http(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _post_logout(cls):
        super()._post_logout()
        request.future_response.set_cookie('color_shade', max_age=0)

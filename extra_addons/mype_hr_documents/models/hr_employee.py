# -*- coding: utf-8 -*-
from odoo import models, fields, api


class HrEmployeeDocumentsExt(models.Model):
    _inherit = "hr.employee"

    digital_signature = fields.Binary(
        string="Firma Digital Registrada",
        copy=False,
        attachment=True,
        help="Firma digitalizada del colaborador capturada desde la app móvil. "
             "Se reutiliza automáticamente en nuevos documentos laborales con su confirmación.",
    )
    has_digital_signature = fields.Boolean(
        string="¿Tiene Firma Registrada?",
        compute="_compute_has_digital_signature",
    )

    @api.depends("digital_signature")
    def _compute_has_digital_signature(self):
        for emp in self:
            emp.has_digital_signature = bool(emp.digital_signature)

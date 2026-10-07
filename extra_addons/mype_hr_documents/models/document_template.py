# -*- coding: utf-8 -*-
from odoo import models, fields, api


class MypeHrDocumentTemplate(models.Model):
    _name = "mype.hr.document.template"
    _description = "Plantilla de Documento Laboral"
    _order = "name asc"

    name = fields.Char(
        string="Nombre del Documento",
        required=True,
    )
    code = fields.Char(
        string="Código de Plantilla",
        required=True,
        copy=False,
        help="Código único identificador del formato (ej. AUTH_IMAGEN_VOZ).",
    )
    document_type = fields.Selection(
        [
            ("auth_image", "Autorización de Uso de Imagen y Voz"),
            ("general", "Documento General"),
        ],
        string="Tipo de Documento",
        default="auth_image",
        required=True,
    )
    requires_manager_signature = fields.Boolean(
        string="Requiere Firma del Empleador / Gerente",
        default=True,
        help="Si está activo, estampa automáticamente la firma configurada en la empresa.",
    )
    report_action_id = fields.Many2one(
        "ir.actions.report",
        string="Acción de Reporte QWeb",
        help="Reporte QWeb utilizado para renderizar el PDF oficial de este documento.",
    )
    description = fields.Text(
        string="Descripción / Propósito",
        help="Detalles sobre cuándo y a quiénes debe emitirse este documento.",
    )
    active = fields.Boolean(
        string="Activo",
        default=True,
    )

    _code_uniq = models.Constraint(
        "UNIQUE(code)",
        "El código de plantilla debe ser único.",
    )

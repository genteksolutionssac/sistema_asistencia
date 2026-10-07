from odoo import models, fields


class MypeHrShift(models.Model):
    _name = "mype.hr.shift"
    _description = "Horario/Turno"
    _order = "name"

    # ==========================
    # General
    # ==========================

    name = fields.Char(
        string="Nombre",
        required=True,
    )

    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        default=lambda self: self.env.company,
        required=True,
    )

    active = fields.Boolean(
        string="Activo",
        default=True,
    )

    # ==========================
    # Reglas de jornada
    # ==========================

    entry_tolerance = fields.Float(
        string="Tolerancia entrada (min)",
        default=10.0,
    )

    exit_tolerance = fields.Float(
        string="Tolerancia salida (min)",
        default=10.0,
    )

    break_minutes = fields.Float(
        string="Tiempo de refrigerio (min)",
        default=60.0,
    )

    allow_overtime = fields.Boolean(
        string="Permite horas extras",
        default=True,
    )

    # ==========================
    # Líneas de turno
    # ==========================

    line_ids = fields.One2many(
        "mype.hr.shift.line",
        "shift_id",
        string="Días de jornada",
    )

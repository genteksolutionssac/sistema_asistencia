from odoo import models, fields, api


class MypeHrShiftLine(models.Model):
    _name = "mype.hr.shift.line"
    _description = "Línea de horario/turno"
    _order = "shift_id, day_of_week"

    # ==========================
    # General
    # ==========================

    shift_id = fields.Many2one(
        "mype.hr.shift",
        string="Horario",
        required=True,
        ondelete="cascade",
    )

    day_of_week = fields.Selection(
        [
            ("0", "Lunes"),
            ("1", "Martes"),
            ("2", "Miércoles"),
            ("3", "Jueves"),
            ("4", "Viernes"),
            ("5", "Sábado"),
            ("6", "Domingo"),
        ],
        string="Día",
        required=True,
    )

    is_working_day = fields.Boolean(
        string="Día laborable",
        default=True,
    )

    # ==========================
    # Jornada
    # ==========================

    entry_time = fields.Float(
        string="Hora de entrada",
    )

    exit_time = fields.Float(
        string="Hora de salida",
    )

    expected_hours = fields.Float(
        string="Horas esperadas",
        compute="_compute_expected_hours",
        store=True,
    )

    # ==========================
    # Restricciones
    # ==========================

    _day_of_week_shift_unique = models.Constraint(
        "UNIQUE(shift_id, day_of_week)",
        "Cada día solo puede tener una jornada por horario.",
    )

    # ==========================
    # Cálculos
    # ==========================

    @api.depends("is_working_day", "entry_time", "exit_time")
    def _compute_expected_hours(self):
        for line in self:
            if not line.is_working_day or not line.entry_time or not line.exit_time:
                line.expected_hours = 0.0
                continue
            hours = line.exit_time - line.entry_time
            if hours < 0:
                hours += 24
            line.expected_hours = round(hours, 4)

from datetime import datetime, time, timedelta

import pytz

from odoo import models, fields, api, _


class MypeAttendance(models.Model):
    _name = "mype.attendance"
    _description = "Registro de asistencia diario"
    _order = "date desc, employee_id"

    # ==========================
    # Identificación
    # ==========================

    employee_id = fields.Many2one(
        "hr.employee",
        string="Empleado",
        required=True,
        index=True,
    )

    department_id = fields.Many2one(
        "hr.department",
        string="Área / Departamento",
        related="employee_id.department_id",
        store=True,
        index=True,
    )

    manager_id = fields.Many2one(
        "hr.employee",
        string="Responsable a cargo",
        related="employee_id.parent_id",
        store=True,
        index=True,
    )

    employee_code = fields.Char(
        string="Código empleado",
    )

    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        required=True,
        index=True,
    )

    date = fields.Date(
        string="Fecha",
        required=True,
        index=True,
    )

    # ==========================
    # Snapshot del contrato/horario
    # ==========================

    contract_id = fields.Many2one(
        "mype.hr.contract",
        string="Contrato",
        help="Contrato vigente del empleado en la fecha (snapshot).",
    )

    shift_id = fields.Many2one(
        "mype.hr.shift",
        string="Horario",
        help="Horario aplicado según el contrato en la fecha (snapshot).",
    )

    is_working_day = fields.Boolean(
        string="Día laborable",
        help="Indica si el día es laborable según el horario.",
    )

    scheduled_entry = fields.Datetime(
        string="Entrada programada",
    )

    scheduled_exit = fields.Datetime(
        string="Salida programada",
    )

    expected_hours = fields.Float(
        string="Horas esperadas",
        digits=(16, 4),
    )

    break_minutes = fields.Float(
        string="Refrigerio (min)",
        digits=(16, 2),
    )

    overtime_allowed = fields.Boolean(
        string="Permite horas extras",
        help="Snapshot de allow_overtime del horario.",
    )

    # ==========================
    # Marcación real
    # ==========================

    entry_time = fields.Datetime(
        string="Entrada real",
    )

    exit_time = fields.Datetime(
        string="Salida real",
    )

    is_complete = fields.Boolean(
        string="Marcación completa",
        help="Tiene entrada y salida.",
    )

    # ==========================
    # Métricas
    # ==========================

    worked_hours = fields.Float(
        string="Horas trabajadas",
        digits=(16, 4),
    )

    late_minutes = fields.Float(
        string="Tardanza (min)",
        digits=(16, 2),
    )

    is_late = fields.Boolean(
        string="Llegó tarde",
    )

    early_exit_minutes = fields.Float(
        string="Salida anticipada (min)",
        digits=(16, 2),
    )

    is_early_exit = fields.Boolean(
        string="Salió temprano",
    )

    overtime_minutes = fields.Float(
        string="Horas extra (min)",
        digits=(16, 2),
    )

    has_overtime = fields.Boolean(
        string="Hizo horas extra",
    )

    # ==========================
    # Estado
    # ==========================

    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("validated", "Validado"),
        ],
        string="Estado",
        default="draft",
    )

    notes = fields.Text(
        string="Notas",
    )

    # ==========================
    # Restricciones
    # ==========================

    _unique_employee_date_company = models.Constraint(
        "UNIQUE(employee_id, date, company_id)",
        "El empleado ya tiene un registro de asistencia para esa fecha.",
    )

    # ==========================
    # Creación y Escritura (Zonas horarias)
    # ==========================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("scheduled_entry"):
                vals["scheduled_entry"] = self._local_to_utc(
                    fields.Datetime.to_datetime(vals["scheduled_entry"])
                )
            if vals.get("scheduled_exit"):
                vals["scheduled_exit"] = self._local_to_utc(
                    fields.Datetime.to_datetime(vals["scheduled_exit"])
                )
        return super().create(vals_list)

    def write(self, vals):
        if "scheduled_entry" in vals and vals["scheduled_entry"]:
            vals["scheduled_entry"] = self._local_to_utc(
                fields.Datetime.to_datetime(vals["scheduled_entry"])
            )
        if "scheduled_exit" in vals and vals["scheduled_exit"]:
            vals["scheduled_exit"] = self._local_to_utc(
                fields.Datetime.to_datetime(vals["scheduled_exit"])
            )
        return super().write(vals)

    # ==========================
    # Mostrar
    # ==========================

    def _compute_display_name(self):
        for attendance in self:
            attendance.display_name = "%s - %s" % (
                attendance.employee_id.name or attendance.employee_code or "?",
                attendance.date,
            )

    def _mype_tz(self):
        """Zona horaria de la empresa o fallback a America/Lima."""
        partner = self.env.company.partner_id
        return partner.tz or self.env.user.tz or 'America/Lima'

    def _local_to_utc(self, dt_naive):
        """Convierte un datetime naive (hora local empresa) a UTC (naive)."""
        if not dt_naive:
            return dt_naive
        tz = pytz.timezone(self._mype_tz())
        return tz.localize(dt_naive).astimezone(pytz.utc).replace(tzinfo=None)

    # ==========================
    # Autocompletado según horario
    # ==========================

    @api.onchange("employee_id", "date", "shift_id")
    def _onchange_shift_defaults(self):
        """Jala los datos del horario al elegir empleado/fecha o cambiar turno.

        Completa contrato vigente, horario, día laborable, horas esperadas,
        refrigerio y la entrada/salida programada según la línea del turno
        del día de la semana.
        """
        self.employee_code = self.employee_id.employee_code if self.employee_id else False

        if self.employee_id and not self.shift_id:
            if hasattr(self.employee_id, "effective_shift_id") and self.employee_id.effective_shift_id:
                self.shift_id = self.employee_id.effective_shift_id
            elif hasattr(self.employee_id.company_id, "default_shift_id") and self.employee_id.company_id.default_shift_id:
                self.shift_id = self.employee_id.company_id.default_shift_id

        contract = False
        if self.employee_id and self.date:
            contract = self._get_contract_on_date(self.employee_id, self.date)
            self.contract_id = contract
            if contract and not self.shift_id:
                self.shift_id = contract.schedule_id

        shift = self.shift_id
        self.break_minutes = shift.break_minutes or 0.0
        self.overtime_allowed = bool(shift.allow_overtime)

        line = False
        if shift and self.date:
            line = self.env["mype.hr.shift.line"].search([
                ("shift_id", "=", shift.id),
                ("day_of_week", "=", str(self.date.weekday())),
            ], limit=1)

        if not line:
            self.is_working_day = False
            self.expected_hours = 0.0
            self.scheduled_entry = False
            self.scheduled_exit = False
            return

        self.is_working_day = bool(line.is_working_day)
        if line.is_working_day and line.entry_time is not False and line.exit_time is not False:
            self.expected_hours = line.expected_hours
            self.scheduled_entry = self._local_to_utc(
                self._hours_to_dt(self.date, line.entry_time))
            self.scheduled_exit = self._local_to_utc(
                self._hours_to_dt(self.date, line.exit_time))
            if self.scheduled_exit <= self.scheduled_entry:
                self.scheduled_exit += timedelta(days=1)
        else:
            self.expected_hours = 0.0
            self.scheduled_entry = False
            self.scheduled_exit = False

    @api.onchange("entry_time", "exit_time", "scheduled_entry", "scheduled_exit",
                  "break_minutes", "shift_id")
    def _onchange_recompute_metrics(self):
        """Recalcula horas trabajadas, tardanzas y salidas anticipadas al
        editar las marcaciones o el horario programado."""
        shift = self.shift_id or self.env["mype.hr.shift"]
        metrics = self._compute_metrics(
            self.entry_time, self.exit_time,
            self.scheduled_entry, self.scheduled_exit,
            self.break_minutes, shift,
        )
        for field_name, value in metrics.items():
            setattr(self, field_name, value)

    # ==========================
    # Métricas
    # ==========================

    @api.model
    def _compute_metrics(self, entry_time, exit_time,
                         scheduled_entry, scheduled_exit,
                         break_minutes, shift):
        """Calcula horas trabajadas, tardanza, salida anticipada y horas extra
        utilizando la hora del día en la zona horaria local para evitar desfases UTC.
        """
        vals = {
            "worked_hours": 0.0,
            "is_complete": False,
            "late_minutes": 0.0,
            "is_late": False,
            "early_exit_minutes": 0.0,
            "is_early_exit": False,
            "overtime_minutes": 0.0,
            "has_overtime": False,
        }

        # Horas trabajadas (resta refrigerio)
        if entry_time and exit_time:
            worked = (exit_time - entry_time).total_seconds() / 3600.0
            worked -= (break_minutes or 0.0) / 60.0
            vals["worked_hours"] = max(round(worked, 4), 0.0)
            vals["is_complete"] = True

        tz_name = self._mype_tz()
        local_tz = pytz.timezone(tz_name)
        utc_tz = pytz.utc

        def to_local_minutes(dt_val):
            """Convierte un datetime a minutos desde inicio del día en tz local.
            
            Asume que:
            - Si dt_val es naive → se interpreta como UTC
            - Si dt_val tiene tz info → se usa directamente
            
            Retorna los minutos locales del día (0 a 1440).
            """
            if not dt_val:
                return None
            
            # Paso 1: Normalizar a datetime consciente de zona horaria UTC
            if dt_val.tzinfo is None:
                # Naive → asumir UTC (marcas del biométrico generalmente vienen así)
                dt_utc = utc_tz.localize(dt_val)
            else:
                # Ya tiene tz info, asegurar que es UTC
                dt_utc = dt_val.astimezone(utc_tz)
            
            # Paso 2: Convertir a zona local
            dt_local = dt_utc.astimezone(local_tz)
            
            # Paso 3: Calcular minutos desde inicio del día local
            local_minutes = dt_local.hour * 60 + dt_local.minute + dt_local.second / 60.0

            return local_minutes

        # Métricas contra el horario programado usando minutos locales del día
        sched_in_min = to_local_minutes(scheduled_entry)
        entry_min = to_local_minutes(entry_time)

        if sched_in_min is not None and entry_min is not None:
            late = entry_min - sched_in_min
            late -= (shift.entry_tolerance or 0.0)

            if late > 0:
                vals["late_minutes"] = round(late, 2)
                vals["is_late"] = True

        sched_out_min = to_local_minutes(scheduled_exit)
        exit_min = to_local_minutes(exit_time)

        if sched_out_min is not None and exit_min is not None:
            early = sched_out_min - exit_min
            early -= (shift.exit_tolerance or 0.0)
            if early > 0:
                vals["early_exit_minutes"] = round(early, 2)
                vals["is_early_exit"] = True

            # Horas extra (si sale después de la programada y está permitido)
            if exit_min > sched_out_min and shift.allow_overtime:
                overtime = exit_min - sched_out_min
                vals["overtime_minutes"] = round(overtime, 2)
                vals["has_overtime"] = True

        return vals

    @api.model
    def _get_contract_on_date(self, employee, day_date):
        return self.env["mype.hr.contract"].search([
            ("employee_id", "=", employee.id),
            ("state", "=", "open"),
            ("date_start", "<=", day_date),
            "|",
            ("date_end", "=", False),
            ("date_end", ">=", day_date),
        ], limit=1)

    @staticmethod
    def _hours_to_dt(day_date, hours):
        hours = float(hours or 0.0)
        h = int(hours) % 24
        m = int(round((hours - int(hours)) * 60))
        if m == 60:
            h = (h + 1) % 24
            m = 0
        return datetime.combine(day_date, time(hour=h, minute=m))

    google_maps_url = fields.Char(
        string="Ver en Google Maps",
        compute="_compute_google_maps_url",
    )

    @api.depends("latitude", "longitude")
    def _compute_google_maps_url(self):
        for att in self:
            if att.latitude and att.longitude:
                att.google_maps_url = f"https://www.google.com/maps/search/?api=1&query={att.latitude},{att.longitude}"
            else:
                att.google_maps_url = False

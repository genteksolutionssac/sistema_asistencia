# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta, time
import pytz
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ResCompanyAttendance(models.Model):
    _inherit = "res.company"

    attendance_latitude = fields.Float(
        string="Latitud de sede",
        digits=(10, 7),
        default=-12.0464,  # Default Lima, Perú
    )
    attendance_longitude = fields.Float(
        string="Longitud de sede",
        digits=(10, 7),
        default=-77.0428,
    )
    allowed_radius_meters = fields.Integer(
        string="Radio permitido (metros)",
        default=100,
        help="Distancia máxima permitida para marcación presencial.",
    )
    default_shift_id = fields.Many2one(
        "mype.hr.shift",
        string="Horario General de la Empresa",
        help="Horario por defecto asignado a todos los colaboradores de la empresa.",
    )
    enable_attendance_reminders = fields.Boolean(
        string="Recordatorios automáticos de marcación",
        default=True,
        help="Envía notificaciones push automáticas a los celulares de los colaboradores "
             "5 minutos antes y 5 minutos después de su horario de entrada.",
    )


class HrEmployeeAttendanceExt(models.Model):
    _inherit = "hr.employee"

    attendance_latitude = fields.Float(
        string="Latitud específica",
        digits=(10, 7),
    )
    attendance_longitude = fields.Float(
        string="Longitud específica",
        digits=(10, 7),
    )
    can_view_dashboard = fields.Boolean(
        string="Activar Dashboard de Control",
        default=False,
        help="Permite a este colaborador visualizar el Dashboard de Control en la App Móvil.",
    )
    use_company_location = fields.Boolean(
        string="Usar ubicación de compañía",
        default=True,
        help="Si está marcado, el empleado debe marcar en la sede configurada de su compañía. "
             "Desmárquelo para indicar una ubicación específica (otra sede/cliente).",
    )
    attendance_location_url = fields.Char(
        string="Mapa del punto de marcación",
        compute="_compute_attendance_location_url",
        help="Enlace a Google Maps con la ubicación efectiva de marcación.",
    )

    use_company_shift = fields.Boolean(
        string="Usar Horario General de la Empresa",
        default=True,
        help="Si está marcado, se aplicará automáticamente el horario general de la empresa.",
    )
    shift_id = fields.Many2one(
        "mype.hr.shift",
        string="Horario / Turno Personalizado",
        help="Asignar un horario específico sólo para este colaborador si no usa el general.",
    )
    effective_shift_id = fields.Many2one(
        "mype.hr.shift",
        string="Horario Efectivo",
        compute="_compute_effective_shift",
        store=True,
        help="Horario que rige para este empleado (general o personalizado).",
    )
    last_entry_pre_reminder_date = fields.Date(
        string="Último recordatorio previo de entrada",
        copy=False,
    )
    last_entry_post_reminder_date = fields.Date(
        string="Último recordatorio post entrada",
        copy=False,
    )
    last_exit_reminder_date = fields.Date(
        string="Último recordatorio de salida",
        copy=False,
    )

    @api.depends("use_company_shift", "shift_id", "company_id.default_shift_id")
    def _compute_effective_shift(self):
        for emp in self:
            if not emp.use_company_shift and emp.shift_id:
                emp.effective_shift_id = emp.shift_id
            else:
                emp.effective_shift_id = emp.company_id.default_shift_id or False

    @api.model
    def _get_default_office_location(self):
        """Obtiene la ubicación de trabajo de tipo 'office' (Oficina) por defecto para la compañía."""
        company = self.env.company
        partner_id = company.partner_id.id if company.partner_id else False
        domain_base = [("location_type", "=", "office")]

        if partner_id:
            loc = self.env["hr.work.location"].search(
                domain_base + [
                    ("company_id", "in", [company.id, False]),
                    ("address_id", "in", [partner_id, False]),
                    "|", ("name", "ilike", "Oficina"), ("name", "ilike", "Office"),
                ],
                limit=1,
            )
            if loc:
                return loc

        loc = self.env["hr.work.location"].search(
            domain_base + [
                ("company_id", "in", [company.id, False]),
                "|", ("name", "ilike", "Oficina"), ("name", "ilike", "Office"),
            ],
            limit=1,
        )
        if loc:
            return loc

        loc = self.env["hr.work.location"].search(
            domain_base + [("company_id", "in", [company.id, False])],
            limit=1,
        )
        if loc:
            return loc

        return self.env["hr.work.location"].search(domain_base, limit=1)

    @api.model
    def default_get(self, fields_list):
        """Al crear un nuevo empleado, asigna por defecto la ubicación 'Oficina'
        y sincroniza los 7 días de la semana a modalidad presencial."""
        res = super().default_get(fields_list)
        default_loc = self._get_default_office_location()
        if default_loc:
            if "work_location_id" in fields_list and not res.get("work_location_id"):
                res["work_location_id"] = default_loc.id

            days = [
                "monday_location_id",
                "tuesday_location_id",
                "wednesday_location_id",
                "thursday_location_id",
                "friday_location_id",
                "saturday_location_id",
                "sunday_location_id",
            ]
            for day in days:
                if day in fields_list and not res.get(day):
                    res[day] = default_loc.id
        return res

    @api.model_create_multi
    def create(self, vals_list):
        days = [
            "monday_location_id",
            "tuesday_location_id",
            "wednesday_location_id",
            "thursday_location_id",
            "friday_location_id",
            "saturday_location_id",
            "sunday_location_id",
        ]
        default_loc = None
        for vals in vals_list:
            if not vals.get("work_location_id"):
                if default_loc is None:
                    default_loc = self._get_default_office_location()
                if default_loc:
                    vals["work_location_id"] = default_loc.id

            loc_id = vals.get("work_location_id")
            if loc_id:
                loc = self.env["hr.work.location"].browse(loc_id)
                if loc.location_type in ("office", "home"):
                    for day in days:
                        if day not in vals or not vals[day]:
                            vals[day] = loc_id
        return super().create(vals_list)

    @api.onchange("work_location_id")
    def _onchange_work_location_id_sync_days(self):
        """Sincroniza la ubicación de los días según la Ubicación de Trabajo seleccionada.

        - Si es 'office': replica esa ubicación de oficina en los 7 días.
        - Si es 'home': replica la ubicación de home office en los 7 días.
        - Si es 'other': limpia los días para permitir asignación personalizada (híbrido).
        """
        if not self.work_location_id:
            return

        loc_type = self.work_location_id.location_type
        days = [
            "monday_location_id",
            "tuesday_location_id",
            "wednesday_location_id",
            "thursday_location_id",
            "friday_location_id",
            "saturday_location_id",
            "sunday_location_id",
        ]

        if loc_type in ("office", "home"):
            for day in days:
                if hasattr(self, day):
                    setattr(self, day, self.work_location_id)
        elif loc_type == "other":
            for day in days:
                if hasattr(self, day):
                    setattr(self, day, False)

    def get_today_modality(self, target_date=None):
        """Determina si para hoy (o la fecha provista) la marcación debe ser presencial o remoto."""
        self.ensure_one()
        from datetime import datetime
        import pytz

        if not target_date:
            tz_name = self.company_id.partner_id.tz or "America/Lima"
            try:
                local_tz = pytz.timezone(tz_name)
                target_date = datetime.now(local_tz).date()
            except Exception:
                target_date = fields.Date.today()

        day_fields = [
            "monday_location_id",
            "tuesday_location_id",
            "wednesday_location_id",
            "thursday_location_id",
            "friday_location_id",
            "saturday_location_id",
            "sunday_location_id",
        ]
        day_field = day_fields[target_date.weekday()]

        # 1. Ubicación excepcional para hoy (si aplica)
        loc = getattr(self, "exceptional_location_id", False)
        # 2. Ubicación del día de la semana
        if not loc and hasattr(self, day_field):
            loc = getattr(self, day_field)
        # 3. Ubicación habitual de trabajo
        if not loc and hasattr(self, "work_location_id"):
            loc = self.work_location_id

        if loc and hasattr(loc, "location_type") and loc.location_type == "home":
            return "remoto"
        return "presencial"


    @api.depends(
        "use_company_location",
        "attendance_latitude",
        "attendance_longitude",
        "company_id.attendance_latitude",
        "company_id.attendance_longitude",
    )
    def _compute_attendance_location_url(self):
        for emp in self:
            if emp.use_company_location:
                lat = emp.company_id.attendance_latitude
                lng = emp.company_id.attendance_longitude
            else:
                lat = emp.attendance_latitude
                lng = emp.attendance_longitude
            emp.attendance_location_url = (
                f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
                if (lat and lng)
                else False
            )


class MypeAttendanceMobileExt(models.Model):
    _inherit = "mype.attendance"

    modality = fields.Selection(
        [
            ("presencial", "Presencial"),
            ("remoto", "Remoto"),
        ],
        string="Modalidad",
        default="presencial",
    )

    latitude = fields.Float(string="Latitud", digits=(10, 7))
    longitude = fields.Float(string="Longitud", digits=(10, 7))

    approval_state = fields.Selection(
        [
            ("auto_approved", "Autoaprobado"),
            ("pending", "Pendiente de aprobación"),
            ("approved", "Aprobado"),
            ("rejected", "Rechazado"),
        ],
        string="Estado de aprobación",
        default="auto_approved",
    )
    origin_source = fields.Selection(
        [
            ("online", "En línea"),
            ("offline_sync", "Sincronizado offline"),
        ],
        string="Origen de registro",
        default="online",
    )

    @api.model
    def _cron_attendance_reminders(self):
        """Revisa los turnos y horarios de los colaboradores para hoy y envía notificaciones push:
        - 5 minutos antes del turno de entrada: aviso preventivo.
        - 5 minutos después del inicio del turno si aún no marcó: aviso de alerta.
        - Al finalizar la jornada si no ha marcado salida: recordatorio de salida.
        """
        _logger.info("Cron: Ejecutando verificación de recordatorios automáticos de asistencia...")
        companies = self.env["res.company"].search([])

        for company in companies:
            if hasattr(company, "enable_attendance_reminders") and not company.enable_attendance_reminders:
                continue

            tz_name = company.partner_id.tz or "America/Lima"
            try:
                local_tz = pytz.timezone(tz_name)
                now_local = datetime.now(local_tz)
            except Exception:
                local_tz = pytz.timezone("America/Lima")
                now_local = datetime.now(local_tz)

            today = now_local.date()
            current_weekday = str(today.weekday())

            # Buscar dispositivos activos que tengan fcm_token registrado
            active_devices = self.env["hr.employee.device"].search([
                ("is_active", "in", ("True", "true", "1")),
                ("fcm_token", "!=", False),
            ])
            if not active_devices:
                continue

            employees = active_devices.mapped("employee_id").filtered(
                lambda e: e.active and e.company_id.id == company.id
            )

            for emp in employees:
                shift = (
                    emp.effective_shift_id
                    if hasattr(emp, "effective_shift_id") and emp.effective_shift_id
                    else (emp.company_id.default_shift_id if hasattr(emp.company_id, "default_shift_id") and emp.company_id.default_shift_id else False)
                )
                if not shift:
                    contract = self._get_contract_on_date(emp, today)
                    shift = contract.schedule_id if contract else False

                if not shift:
                    continue

                line = self.env["mype.hr.shift.line"].search([
                    ("shift_id", "=", shift.id),
                    ("day_of_week", "=", current_weekday),
                ], limit=1)

                if not line or not line.is_working_day or line.entry_time is False:
                    continue

                first_name = (emp.name or "").strip().split()[0]

                # Hora de entrada programada
                entry_naive = self._hours_to_dt(today, line.entry_time)
                entry_dt = local_tz.localize(entry_naive)
                diff_entry_min = (entry_dt - now_local).total_seconds() / 60.0

                # Verificar si ya marcó hoy
                att = self.search([
                    ("employee_id", "=", emp.id),
                    ("date", "=", today),
                ], limit=1)
                has_checked_in = bool(att and att.entry_time)
                has_checked_out = bool(att and att.exit_time)

                entry_str = entry_naive.strftime("%I:%M %p")

                # Caso 1: 5 minutos ANTES de la entrada (ventana de 0 a 10 min antes)
                if 0.0 <= diff_entry_min <= 10.0 and emp.last_entry_pre_reminder_date != today:
                    if not has_checked_in:
                        _logger.info(f"FCM Reminder: Enviando pre-aviso de entrada a {emp.name} (Turno: {entry_str})")
                        self.env["hr.employee.device"].send_push_to_employees(
                            emp,
                            title="⏰ ¡Ya casi es hora de ingresar!",
                            body=f"Hola {first_name}, tu turno inicia a las {entry_str}. Recuerda registrar tu marcación.",
                            data={
                                "type": "attendance_reminder",
                                "sub_type": "pre_entry",
                                "route": "/home",
                            },
                            web_link="/",
                        )
                        emp.sudo().write({"last_entry_pre_reminder_date": today})

                # Caso 2: 5 minutos DESPUÉS del inicio del turno si NO ha marcado (ventana de 4 a 35 min)
                elif -35.0 <= diff_entry_min <= -4.0 and emp.last_entry_post_reminder_date != today:
                    if not has_checked_in:
                        _logger.info(f"FCM Reminder: Enviando alerta de entrada no marcada a {emp.name} (Inició: {entry_str})")
                        self.env["hr.employee.device"].send_push_to_employees(
                            emp,
                            title="⚠️ ¿Olvidaste marcar tu entrada?",
                            body=f"Hola {first_name}, tu horario inició a las {entry_str} y aún no registras tu asistencia. ¡No olvides marcar!",
                            data={
                                "type": "attendance_reminder",
                                "sub_type": "post_entry",
                                "route": "/home",
                            },
                            web_link="/",
                        )
                        emp.sudo().write({"last_entry_post_reminder_date": today})

                # Caso 3: Recordatorio de salida si marcó entrada y ya llegó la hora de salida
                if line.exit_time is not False and has_checked_in and not has_checked_out:
                    exit_naive = self._hours_to_dt(today, line.exit_time)
                    if line.exit_time < line.entry_time:
                        exit_naive += timedelta(days=1)
                    exit_dt = local_tz.localize(exit_naive)
                    diff_exit_min = (now_local - exit_dt).total_seconds() / 60.0

                    if 0.0 <= diff_exit_min <= 25.0 and emp.last_exit_reminder_date != today:
                        exit_str = exit_naive.strftime("%I:%M %p")
                        _logger.info(f"FCM Reminder: Enviando aviso de salida a {emp.name} (Salida: {exit_str})")
                        self.env["hr.employee.device"].send_push_to_employees(
                            emp,
                            title="🚪 Fin de jornada laboral",
                            body=f"Hola {first_name}, tu horario de salida fue a las {exit_str}. No olvides registrar tu salida.",
                            data={
                                "type": "attendance_reminder",
                                "sub_type": "exit",
                                "route": "/home",
                            },
                            web_link="/",
                        )
                        emp.sudo().write({"last_exit_reminder_date": today})

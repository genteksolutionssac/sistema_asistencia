from datetime import datetime, date

from odoo.tests import TransactionCase

MONDAY = date(2026, 8, 10)      # weekday() == 0
SUNDAY = date(2026, 8, 9)       # weekday() == 6


def _naive(day, hours, minutes=0):
    """Datetime naive (UTC) para un día/hora dados."""
    return datetime(day.year, day.month, day.day, hours, minutes)


class TestAttendance(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env["res.company"].create({"name": "Empresa Test"})
        # Fijar tz de la empresa para un comportamiento determinista (Lima, UTC-5).
        self.company.partner_id.tz = "America/Lima"
        self.env = self.env(context={
            "company_id": self.company.id,
            "allowed_company_ids": [self.company.id],
        })
        self.employee = self.env["hr.employee"].create({
            "name": "Ana Torres",
            "employee_code": "EMP003",
        })
        self.shift = self.env["mype.hr.shift"].create({
            "name": "Turno 8h",
            "entry_tolerance": 5.0,
            "exit_tolerance": 5.0,
            "break_minutes": 60.0,
            "allow_overtime": True,
        })
        self.env["mype.hr.shift.line"].create({
            "shift_id": self.shift.id,
            "day_of_week": "0",          # Lunes
            "entry_time": 8.0,
            "exit_time": 17.0,
            "is_working_day": True,
        })
        self.contract = self.env["mype.hr.contract"].create({
            "employee_id": self.employee.id,
            "date_start": date(2026, 1, 1),
            "state": "open",
            "schedule_id": self.shift.id,
            "wage": 1500.0,
            "wage_type": "monthly",
        })

    def _mark_attendance(self, entry_h=None, exit_h=None, day=MONDAY,
                         working=True, minutes=0):
        """Crea una asistencia como la app móvil: entrada/salida en hora UTC y
        horario programado en hora local (el modelo lo convierte a UTC)."""
        utc_offset = 5  # UTC-5 -> hora UTC = hora local + 5
        entry_utc = _naive(day, entry_h + utc_offset, minutes) if entry_h is not None else False
        exit_utc = _naive(day, exit_h + utc_offset) if exit_h is not None else False

        att = self.env["mype.attendance"].create({
            "employee_id": self.employee.id,
            "employee_code": self.employee.employee_code,
            "company_id": self.company.id,
            "date": day,
            "contract_id": self.contract.id,
            "shift_id": self.shift.id,
            "is_working_day": working,
            "scheduled_entry": _naive(day, 8) if working else False,
            "scheduled_exit": _naive(day, 17) if working else False,
            "expected_hours": 9.0 if working else 0.0,
            "break_minutes": self.shift.break_minutes or 0.0,
            "overtime_allowed": bool(self.shift.allow_overtime),
            "entry_time": entry_utc,
            "exit_time": exit_utc,
        })
        att.write(self.env["mype.attendance"]._compute_metrics(
            att.entry_time, att.exit_time,
            att.scheduled_entry, att.scheduled_exit,
            att.break_minutes, att.shift_id,
        ))
        return att

    def test_full_day_worked_and_expected(self):
        att = self._mark_attendance(entry_h=8, exit_h=17)
        self.assertTrue(att.is_complete)
        self.assertTrue(att.is_working_day)
        # 9h de jornada menos 60 min de refrigerio = 8h trabajadas
        self.assertAlmostEqual(att.worked_hours, 8.0, places=3)
        # Horas esperadas = salida programada - entrada programada (sin refrigerio)
        self.assertEqual(att.expected_hours, 9.0)
        self.assertEqual(att.break_minutes, 60.0)
        self.assertFalse(att.is_late)
        self.assertFalse(att.is_early_exit)
        self.assertFalse(att.has_overtime)

    def test_late_detection(self):
        att = self._mark_attendance(entry_h=8, exit_h=17, minutes=10)
        self.assertTrue(att.is_late)
        self.assertEqual(att.late_minutes, 5.0)   # 10 - tolerancia 5

    def test_early_exit_detection(self):
        att = self._mark_attendance(entry_h=8, exit_h=17)
        att.exit_time = _naive(MONDAY, 16 + 5, 50)  # salida local 16:50
        att.write(self.env["mype.attendance"]._compute_metrics(
            att.entry_time, att.exit_time,
            att.scheduled_entry, att.scheduled_exit,
            att.break_minutes, att.shift_id,
        ))
        self.assertTrue(att.is_early_exit)
        self.assertEqual(att.early_exit_minutes, 5.0)

    def test_overtime_detection(self):
        att = self._mark_attendance(entry_h=8, exit_h=18)
        self.assertTrue(att.has_overtime)
        self.assertEqual(att.overtime_minutes, 60.0)
        self.assertTrue(att.overtime_allowed)

    def test_overtime_not_allowed(self):
        self.shift.allow_overtime = False
        att = self._mark_attendance(entry_h=8, exit_h=18)
        self.assertFalse(att.has_overtime)

    def test_non_working_day(self):
        att = self._mark_attendance(entry_h=10, exit_h=14, day=SUNDAY, working=False)
        self.assertFalse(att.is_working_day)
        self.assertFalse(att.scheduled_entry)
        # 4h - 1h refrigerio = 3h
        self.assertAlmostEqual(att.worked_hours, 3.0, places=3)

    def test_incomplete_day(self):
        att = self._mark_attendance(entry_h=8)
        self.assertFalse(att.is_complete)
        self.assertFalse(att.exit_time)
        self.assertEqual(att.worked_hours, 0.0)

    def test_approval_default_auto_approved(self):
        att = self._mark_attendance(entry_h=8, exit_h=17)
        self.assertEqual(att.approval_state, "auto_approved")
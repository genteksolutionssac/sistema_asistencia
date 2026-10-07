from odoo.tests import TransactionCase


class TestHrShiftLine(TransactionCase):

    def _create_shift(self, break_minutes=0.0):
        return self.env["mype.hr.shift"].create({
            "name": "Turno Test",
            "break_minutes": break_minutes,
        })

    def test_expected_hours_same_day(self):
        shift = self._create_shift()
        line = self.env["mype.hr.shift.line"].create({
            "shift_id": shift.id,
            "day_of_week": "0",
            "entry_time": 8.0,
            "exit_time": 17.0,
            "is_working_day": True,
        })
        line._compute_expected_hours()
        self.assertEqual(line.expected_hours, 9.0)

    def test_expected_hours_with_break(self):
        shift = self._create_shift(break_minutes=60.0)
        line = self.env["mype.hr.shift.line"].create({
            "shift_id": shift.id,
            "day_of_week": "1",
            "entry_time": 8.0,
            "exit_time": 17.0,
            "is_working_day": True,
        })
        line._compute_expected_hours()
        # Horas esperadas = salida programada - entrada programada (el refrigerio
        # se muestra por separado y se resta solo de las horas trabajadas).
        self.assertEqual(line.expected_hours, 9.0)

    def test_expected_hours_overnight(self):
        shift = self._create_shift()
        line = self.env["mype.hr.shift.line"].create({
            "shift_id": shift.id,
            "day_of_week": "2",
            "entry_time": 22.0,
            "exit_time": 6.0,
            "is_working_day": True,
        })
        line._compute_expected_hours()
        self.assertEqual(line.expected_hours, 8.0)

    def test_expected_hours_non_working_day(self):
        shift = self._create_shift()
        line = self.env["mype.hr.shift.line"].create({
            "shift_id": shift.id,
            "day_of_week": "3",
            "entry_time": 8.0,
            "exit_time": 17.0,
            "is_working_day": False,
        })
        line._compute_expected_hours()
        self.assertEqual(line.expected_hours, 0.0)

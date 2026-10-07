from odoo.tests import TransactionCase
from odoo.exceptions import ValidationError
from datetime import date


class TestHrContract(TransactionCase):

    def setUp(self):
        super().setUp()
        self.employee = self.env["hr.employee"].create({
            "name": "Juan Pérez",
        })

    def _create_contract(self, **kwargs):
        vals = {
            "employee_id": self.employee.id,
            "date_start": kwargs.pop("date_start", date(2026, 1, 1)),
            "wage": 1130.0,
        }
        vals.update(kwargs)
        return self.env["mype.hr.contract"].create(vals)

    def test_contract_valid_dates(self):
        contract = self._create_contract(
            date_start=date(2026, 1, 1),
            date_end=date(2026, 12, 31),
        )
        self.assertTrue(contract)

    def test_contract_end_before_start_rejected(self):
        with self.assertRaises(ValidationError):
            self._create_contract(
                date_start=date(2026, 12, 31),
                date_end=date(2026, 1, 1),
            )

    def test_contract_negative_wage_rejected(self):
        with self.assertRaises(ValidationError):
            self._create_contract(wage=-100.0)

    def test_contract_overlap_rejected(self):
        self._create_contract(
            date_start=date(2026, 1, 1),
            date_end=date(2026, 12, 31),
            state="open",
        )
        with self.assertRaises(ValidationError):
            self._create_contract(
                date_start=date(2026, 6, 1),
                date_end=date(2027, 6, 1),
                state="open",
            )

    def test_contract_sequential_not_overlap_ok(self):
        self._create_contract(
            date_start=date(2026, 1, 1),
            date_end=date(2026, 6, 30),
            state="open",
        )
        contract2 = self._create_contract(
            date_start=date(2026, 7, 1),
            date_end=date(2026, 12, 31),
            state="open",
        )
        self.assertTrue(contract2)

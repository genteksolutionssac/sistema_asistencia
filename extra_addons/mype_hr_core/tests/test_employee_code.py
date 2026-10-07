from odoo.tests import TransactionCase


class TestEmployeeCode(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env.company

    def test_auto_generated_employee_code(self):
        employee = self.env["hr.employee"].create({"name": "Auto Uno"})
        self.assertTrue(employee.employee_code)
        self.assertTrue(employee.employee_code.startswith("EMP"))

    def test_sequence_increments(self):
        first = self.env["hr.employee"].create({"name": "Auto Uno"})
        second = self.env["hr.employee"].create({"name": "Auto Dos"})
        num_first = int(first.employee_code.replace("EMP", ""))
        num_second = int(second.employee_code.replace("EMP", ""))
        self.assertEqual(num_second, num_first + 1)

    def test_custom_prefix(self):
        self.company.employee_code_prefix = "PLA"
        self.company.employee_code_padding = 4
        employee = self.env["hr.employee"].create({"name": "Auto Prefijo"})
        self.assertTrue(employee.employee_code.startswith("PLA"))
        self.assertEqual(len(employee.employee_code), 7)  # PLA + 4 dígitos

    def test_manual_code_not_overridden(self):
        employee = self.env["hr.employee"].create({
            "name": "Manual",
            "employee_code": "M-100",
        })
        self.assertEqual(employee.employee_code, "M-100")

    def _fresh_company(self):
        """Empresa de prueba sin empleados (determinista)."""
        return self.env["res.company"].create({"name": "Test Co"})

    def test_sequence_avoids_existing_code(self):
        company = self._fresh_company()
        self.env["hr.employee"].create({
            "name": "Existente",
            "employee_code": "EMP001",
            "company_id": company.id,
        })
        newbie = self.env["hr.employee"].create({
            "name": "Nuevo",
            "company_id": company.id,
        })
        self.assertEqual(newbie.employee_code, "EMP002")

    def test_next_number_editable(self):
        company = self._fresh_company()
        company._ensure_employee_sequence()
        company.employee_code_next = 50
        employee = self.env["hr.employee"].create({
            "name": "Correlativo",
            "company_id": company.id,
        })
        self.assertEqual(employee.employee_code, "EMP050")

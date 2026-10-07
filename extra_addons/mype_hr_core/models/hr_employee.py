from datetime import date
from odoo import models, fields, api


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    # ==========================
    # Identificación interna
    # ==========================

    employee_code = fields.Char(
        string="Código de empleado",
        copy=False,
        index=True,
        tracking=True,
        help="Se genera automáticamente con el prefijo configurado en la empresa "
             "(editable). Debe coincidir con el código enviado por el reloj "
             "biométrico.",
    )
    # ==========================
    # Datos de planilla
    # ==========================

    bank_account_id = fields.Many2one(
        "res.partner.bank",
        string="Cuenta bancaria",
    )

    # ==========================
    # Datos del contrato vigente (solo lectura)
    # ==========================

    active_contract_id = fields.Many2one(
        "mype.hr.contract",
        string="Contrato vigente",
        compute="_compute_active_contract",
        store=True,
        help="Contrato en estado Vigente cuya fecha cubre hoy. "
             "Sus datos se muestran sólo para consulta.",
    )

    contract_wage = fields.Monetary(
        string="Sueldo base",
        compute="_compute_active_contract",
        store=True,
        readonly=True,
        currency_field="contract_currency_id",
    )

    contract_currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_active_contract",
        store=True,
        readonly=True,
    )

    contract_type = fields.Selection(
        [
            ("indefinite", "Indefinido"),
            ("fixed_term", "A plazo fijo"),
            ("part_time", "Tiempo parcial"),
            ("temporary", "Temporal"),
        ],
        compute="_compute_active_contract",
        string="Tipo de contrato",
        store=True,
        readonly=True,
    )

    contract_date_start = fields.Date(
        compute="_compute_active_contract",
        string="Inicio del contrato",
        store=True,
        readonly=True,
    )

    contract_date_end = fields.Date(
        compute="_compute_active_contract",
        string="Fin del contrato",
        store=True,
        readonly=True,
    )

    contract_wage_type = fields.Selection(
        [
            ("monthly", "Mensual"),
            ("daily", "Diario"),
            ("hourly", "Por hora"),
        ],
        compute="_compute_active_contract",
        string="Periodicidad del sueldo",
        store=True,
        readonly=True,
    )

    contract_schedule_id = fields.Many2one(
        "mype.hr.shift",
        compute="_compute_active_contract",
        string="Horario/Turno",
        store=True,
        readonly=True,
    )

    # ==========================
    # Estado laboral
    # ==========================

    employment_state = fields.Selection(
        [
            ("active", "Activo"),
            ("vacation", "Vacaciones"),
            ("license", "Licencia"),
            ("suspended", "Suspendido"),
            ("retired", "Cese"),
        ],
        string="Estado laboral",
        default="active",
        tracking=True,
    )

    # ==========================
    # Restricciones
    # ==========================

    _employee_code_company_unique = models.Constraint(
        "UNIQUE(employee_code, company_id)",
        "El código de empleado debe ser único por compañía.",
    )

    # ==========================
    # Asignación automática de Gerente según Departamento
    # ==========================

    @api.onchange("department_id")
    def _onchange_department_id_sync_manager(self):
        """Al seleccionar un departamento, asigna automáticamente como Gerente / Responsable
        (parent_id) al encargado configurado en dicho departamento."""
        if self.department_id and self.department_id.manager_id:
            # Evitar auto-asignarse si el colaborador que se edita ya es el gerente del área
            if not self.id or self.department_id.manager_id.id != self.id:
                self.parent_id = self.department_id.manager_id

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "parent_id" in fields_list and not res.get("parent_id") and res.get("department_id"):
            dep = self.env["hr.department"].browse(res["department_id"])
            if dep.manager_id:
                res["parent_id"] = dep.manager_id.id
        return res

    # ==========================
    # Generación automática del código
    # ==========================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("employee_code"):
                company = self.env["res.company"].browse(
                    vals.get("company_id") or self.env.company.id
                )
                company._ensure_employee_sequence()
                vals["employee_code"] = company.employee_sequence_id.next_by_id()

            if vals.get("department_id") and not vals.get("parent_id"):
                dep = self.env["hr.department"].browse(vals["department_id"])
                if dep.manager_id:
                    vals["parent_id"] = dep.manager_id.id

        return super().create(vals_list)

    # ==========================
    # Contrato vigente del empleado
    # ==========================

    @api.depends("company_id")
    def _compute_active_contract(self):
        contract_model = self.env["mype.hr.contract"]
        today = fields.Date.context_today(self)
        for employee in self:
            # 1. Intentar buscar contrato abierto que cubra hoy
            contract = contract_model.search([
                ("employee_id", "=", employee.id),
                ("company_id", "=", employee.company_id.id),
                ("state", "=", "open"),
                ("date_start", "<=", today),
                "|",
                ("date_end", "=", False),
                ("date_end", ">=", today),
            ], limit=1)
            # 2. Si no hay uno exacto para hoy, tomar el último contrato abierto del empleado
            if not contract:
                contract = contract_model.search([
                    ("employee_id", "=", employee.id),
                    ("company_id", "=", employee.company_id.id),
                    ("state", "=", "open"),
                ], order="date_start desc", limit=1)
            # 3. Si aun así no hay abierto, tomar cualquier contrato (incluso borrador) para ayudar a visualizar
            if not contract:
                contract = contract_model.search([
                    ("employee_id", "=", employee.id),
                    ("company_id", "=", employee.company_id.id),
                ], order="date_start desc", limit=1)

            employee.active_contract_id = contract
            employee.contract_wage = contract.wage if contract else 0.0
            employee.contract_currency_id = (contract and contract.currency_id) or employee.company_id.currency_id
            employee.contract_type = contract.contract_type if contract else False
            employee.contract_date_start = contract.date_start if contract else False
            employee.contract_date_end = contract.date_end if contract else False
            employee.contract_wage_type = contract.wage_type if contract else False
            employee.contract_schedule_id = contract.schedule_id if contract else False

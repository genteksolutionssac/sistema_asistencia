from odoo import models, fields, api


class ResCompany(models.Model):
    _inherit = "res.company"


    # ==========================
    # Datos de Representación Legal y Contratos Laborales
    # ==========================

    legal_representative_name = fields.Char(
        string="Nombre del Representante Legal",
        help="Nombre completo del representante legal o apoderado para contratos y convenios.",
    )
    legal_representative_job = fields.Char(
        string="Cargo del Representante Legal",
        help="Cargo del representante legal (ej. Gerente General, Administrador).",
    )
    legal_representative_vat = fields.Char(
        string="DNI / Documento del Representante Legal",
        help="Número de DNI o documento de identidad del representante legal.",
    )
    company_signature_image = fields.Binary(
        string="Firma y Sello de la Empresa",
        help="Firma y sello digitalizados del representante legal para estampar en contratos y documentos.",
    )
    company_registry_entry = fields.Char(
        string="Partida Registral (SUNARP)",
        help="Número de partida registral de la empresa inscrita en SUNARP.",
    )
    company_remype_number = fields.Char(
        string="Resolución / N° REMYPE",
        help="Número de registro o resolución de acreditación REMYPE.",
    )
    company_contract_logo = fields.Binary(
        string="Logo para Contratos / Documentos",
        help="Logo en alta resolución para el encabezado de contratos y documentos oficiales.",
    )
    company_activity_description = fields.Text(
        string="Giro o Actividad Principal",
        help="Descripción de la actividad o giro principal de la empresa para cláusulas de contratos.",
    )

    # ==========================
    # Configuración del código de empleado
    # ==========================

    employee_code_prefix = fields.Char(
        string="Prefijo código empleado",
        default="EMP",
        help="Prefijo del código automático de empleado (ej. EMP → EMP001).",
    )

    employee_code_padding = fields.Integer(
        string="Dígitos del correlativo",
        default=3,
        help="Cantidad de dígitos del correlativo (ej. 3 → 001).",
    )

    employee_sequence_id = fields.Many2one(
        "ir.sequence",
        string="Secuencia de empleados",
        ondelete="restrict",
        copy=False,
    )

    employee_code_next = fields.Integer(
        string="Siguiente correlativo",
        compute="_compute_employee_code_next",
        inverse="_inverse_employee_code_next",
        help="Próximo número correlativo que se asignará al crear un empleado.",
    )

    # ==========================
    # Reglas de planilla (FASE 5)
    # ==========================

    payroll_currency_id = fields.Many2one(
        "res.currency",
        string="Moneda de planilla",
        default=lambda self: self.env.ref('base.PEN', raise_if_not_found=False) or self.env.company.currency_id,
        help="Moneda en la que se expresan las planillas.",
    )

    essalud_rate = fields.Float(
        string="EsSalud (%)",
        default=9.0,
        help="Aporte del empleador a EsSalud (porcentaje de la remuneración "
             "computable).",
    )

    family_allowance_amount = fields.Monetary(
        string="Asignación familiar",
        currency_field="payroll_currency_id",
        default=113.0,
        help="Monto mensual de asignación familiar (10% de la RMV) para "
             "empleados que la tengan habilitada en el contrato.",
    )

    overtime_first_hours = fields.Float(
        string="Horas extra al 1.25",
        default=2.0,
        help="Primeras N horas extra diarias que se pagan con el sobretasa "
             "inferior.",
    )

    overtime_rate_first = fields.Float(
        string="Sobretasa primeras horas",
        default=1.25,
        help="Multiplicador de la hora extra para las primeras horas (norma: "
             "1.25).",
    )

    overtime_rate_after = fields.Float(
        string="Sobretasa siguientes horas",
        default=2.0,
        help="Multiplicador de la hora extra para las horas siguientes (norma: "
             "2.00).",
    )

    # ==========================
    # Ciclo de vida de la secuencia
    # ==========================

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        for company in companies:
            company._ensure_employee_sequence()
        return companies

    def write(self, vals):
        result = super().write(vals)
        for company in self:
            company._ensure_employee_sequence()
        return result

    def _ensure_employee_sequence(self):
        """Crea o sincroniza la secuencia de códigos de empleado de la empresa."""
        self.ensure_one()
        prefix = self.employee_code_prefix or "EMP"
        padding = self.employee_code_padding or 3
        next_available = self._next_available_number(prefix)
        sequence = self.employee_sequence_id
        if not sequence:
            sequence = self.env["ir.sequence"].create({
                "name": "Código de empleado - %s" % self.name,
                "code": "mype.hr.employee.code",
                "prefix": prefix,
                "padding": padding,
                "company_id": self.id,
                "implementation": "standard",
                "number_next": next_available,
            })
            self.employee_sequence_id = sequence
        else:
            values = {}
            if sequence.prefix != prefix or sequence.padding != padding:
                values.update({
                    "prefix": prefix,
                    "padding": padding,
                })
            if "prefix" in values or sequence.number_next_actual < next_available:
                values["number_next_actual"] = next_available
            if values:
                sequence.write(values)

    def _next_available_number(self, prefix):
        """Devuelve el siguiente correlativo libre para el prefijo dado
        (max codigo existente + 1). Evita colisiones con códigos manuales."""
        employees = self.env["hr.employee"].search([
            ("company_id", "=", self.id),
        ])
        max_number = 0
        for employee in employees:
            code = employee.employee_code or ""
            if code.startswith(prefix):
                suffix = code[len(prefix):]
                if suffix.isdigit():
                    max_number = max(max_number, int(suffix))
        return max_number + 1

    # ==========================
    # Correlativo visible/editable
    # ==========================

    def _compute_employee_code_next(self):
        for company in self:
            company.employee_code_next = \
                company.employee_sequence_id.number_next_actual or 1

    def _inverse_employee_code_next(self):
        for company in self:
            company._ensure_employee_sequence()
            if company.employee_sequence_id:
                company.employee_sequence_id.number_next_actual = \
                    company.employee_code_next or 1

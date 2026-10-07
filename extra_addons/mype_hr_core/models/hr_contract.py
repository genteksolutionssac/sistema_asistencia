# -*- coding: utf-8 -*-
import base64
import io
import os
import tempfile
from datetime import date
import docx
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

try:
    from docxtpl import DocxTemplate, InlineImage
except ImportError:
    DocxTemplate = None

try:
    import win32com.client
    import pythoncom
except ImportError:
    win32com = None


def number_to_words_es(amount):
    """Convierte un monto numérico a formato textual en Soles peruanos."""
    units = ['', 'un', 'dos', 'tres', 'cuatro', 'cinco', 'seis', 'siete', 'ocho', 'nueve']
    tens = ['', 'diez', 'veinte', 'treinta', 'cuarenta', 'cincuenta', 'sesenta', 'setenta', 'ochenta', 'noventa']
    teens = ['diez', 'once', 'doce', 'trece', 'catorce', 'quince', 'dieciséis', 'diecisiete', 'dieciocho', 'diecinueve']
    twenties = ['veinte', 'veintiuno', 'veintidós', 'veintitrés', 'veinticuatro', 'veinticinco', 'veintiséis', 'veintisiete', 'veintiocho', 'veintinueve']
    hundreds = ['', 'ciento', 'doscientos', 'trescientos', 'cuatrocientos', 'quinientos', 'seiscientos', 'setecientos', 'ochocientos', 'novecientos']

    int_part = int(amount)
    cents = int(round((amount - int_part) * 100))

    if int_part == 0:
        words = 'cero'
    elif int_part == 100:
        words = 'cien'
    else:
        def convert_triplet(n):
            if n == 0:
                return ''
            if n == 100:
                return 'cien'
            c = n // 100
            d = (n % 100) // 10
            u = n % 10
            res = []
            if c > 0:
                res.append(hundreds[c])
            du = n % 100
            if du >= 10 and du < 20:
                res.append(teens[du - 10])
            elif du >= 20 and du < 30:
                res.append(twenties[du - 20])
            else:
                if d > 0:
                    if u > 0:
                        res.append(tens[d] + ' y ' + units[u])
                    else:
                        res.append(tens[d])
                elif u > 0:
                    res.append(units[u])
            return ' '.join(res)

        thousands = int_part // 1000
        remainder = int_part % 1000
        parts = []
        if thousands > 0:
            if thousands == 1:
                parts.append('mil')
            else:
                parts.append(convert_triplet(thousands) + ' mil')
        if remainder > 0:
            parts.append(convert_triplet(remainder))
        words = ' '.join(parts)

    return f"{words} con {cents:02d}/100 Soles"


class MypeHrContract(models.Model):
    _name = "mype.hr.contract"
    _description = "Contrato laboral"
    _inherit = ["mail.thread"]
    _order = "date_start desc"

    # ==========================
    # General
    # ==========================

    name = fields.Char(
        string="Contrato",
        required=True,
        default=lambda self: self._default_name(),
        tracking=True,
    )

    employee_id = fields.Many2one(
        "hr.employee",
        string="Empleado",
        required=True,
        index=True,
        tracking=True,
    )

    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        default=lambda self: self.env.company,
        required=True,
    )

    # ==========================
    # Vigencia
    # ==========================

    date_start = fields.Date(
        string="Fecha de inicio",
        required=True,
        tracking=True,
    )

    date_end = fields.Date(
        string="Fecha de fin",
        tracking=True,
    )

    duration_text = fields.Char(
        string="Duración del contrato",
        compute="_compute_contract_duration",
        store=True,
        help="Cálculo textual del tiempo de vigencia del contrato.",
    )

    contract_type = fields.Selection(
        [
            ("indefinite", "Indefinido"),
            ("fixed_term", "A plazo fijo / Modalidad"),
            ("part_time", "Tiempo parcial"),
            ("temporary", "Temporal"),
        ],
        string="Tipo de contrato",
        default="fixed_term",
        required=True,
        tracking=True,
    )

    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("open", "Vigente"),
            ("closed", "Finalizado"),
            ("cancel", "Cancelado"),
        ],
        string="Estado",
        default="draft",
        tracking=True,
    )

    # ==========================
    # Puesto y Área
    # ==========================

    job_id = fields.Many2one(
        "hr.job",
        string="Puesto",
        tracking=True,
    )

    department_id = fields.Many2one(
        "hr.department",
        string="Departamento",
        tracking=True,
    )

    cost_center = fields.Char(
        string="Centro de costo",
    )

    # ==========================
    # Remuneración
    # ==========================

    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        store=True,
    )

    wage = fields.Monetary(
        string="Sueldo bruto/base",
        currency_field="currency_id",
        required=True,
        tracking=True,
    )

    wage_in_words = fields.Char(
        string="Sueldo en letras",
        compute="_compute_wage_in_words",
        store=True,
    )

    wage_type = fields.Selection(
        [
            ("monthly", "Mensual"),
            ("daily", "Diario"),
            ("hourly", "Por hora"),
        ],
        string="Periodicidad del sueldo",
        default="monthly",
        required=True,
    )

    # ==========================
    # Jornada y beneficios
    # ==========================

    schedule_id = fields.Many2one(
        "mype.hr.shift",
        string="Horario/Turno",
        tracking=True,
    )


    has_family_allowance = fields.Boolean(
        string="Asignación familiar",
        default=False,
        tracking=True,
    )

    # ==========================
    # Plantillas y Cláusulas Dinámicas (Word/PDF)
    # ==========================

    template_id = fields.Many2one(
        "mype.hr.contract.template",
        string="Plantilla Word (.docx)",
        tracking=True,
        help="Plantilla con variables {{ variable }} para la generación del contrato.",
    )

    legal_modality = fields.Char(
        string="Modalidad contractual",
        default="Inicio de Nueva Actividad",
        help="Nombre de la modalidad contractual (ej. Inicio de Nueva Actividad, Necesidad de Mercado, etc.).",
    )

    legal_base = fields.Char(
        string="Base legal",
        default="artículo 57 del Texto Único Ordenado del Decreto Legislativo N° 728",
        help="Dispositivo legal o artículo de amparo.",
    )

    objective_cause = fields.Text(
        string="Causa objetiva / Justificación",
        help="Causa objetiva que justifica la temporalidad de la contratación.",
    )

    job_functions_custom = fields.Text(
        string="Funciones del cargo (personalizadas)",
        help="Funciones específicas para este contrato. Si se deja vacío, toma las funciones del Puesto de Trabajo.",
    )

    trial_period_months = fields.Integer(
        string="Periodo de prueba (meses)",
        default=3,
        help="Meses de período de prueba pactados.",
    )

    work_modality = fields.Selection(
        [
            ("presencial", "Presencial"),
            ("remoto", "Remoto"),
            ("hibrido", "Híbrido"),
        ],
        string="Modalidad de trabajo",
        default="presencial",
        tracking=True,
    )

    signing_city = fields.Char(
        string="Ciudad de suscripción",
        default="Lima",
    )

    signing_date = fields.Date(
        string="Fecha de suscripción",
        default=fields.Date.context_today,
    )

    # ==========================
    # Cómputos
    # ==========================

    @api.depends("wage")
    def _compute_wage_in_words(self):
        for contract in self:
            if contract.wage:
                contract.wage_in_words = number_to_words_es(contract.wage)
            else:
                contract.wage_in_words = ""

    @api.depends("date_start", "date_end", "contract_type")
    def _compute_contract_duration(self):
        months_es = {
            1: "un", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco", 6: "seis",
            7: "siete", 8: "ocho", 9: "nueve", 10: "diez", 11: "once", 12: "doce",
            24: "veinticuatro", 36: "treinta y seis"
        }
        for contract in self:
            if contract.contract_type == "indefinite" or not contract.date_end:
                contract.duration_text = "Indeterminado"
                continue
            if contract.date_start and contract.date_end:
                days = (contract.date_end - contract.date_start).days + 1
                months = round(days / 30.4)
                if months <= 0:
                    months = 1
                if months == 12:
                    contract.duration_text = "doce (12) meses"
                elif months in months_es:
                    contract.duration_text = f"{months_es[months]} ({months}) meses"
                else:
                    contract.duration_text = f"{months} meses"
            else:
                contract.duration_text = ""

    @api.onchange("template_id")
    def _onchange_template_id(self):
        if self.template_id:
            if self.template_id.legal_modality_title:
                self.legal_modality = self.template_id.legal_modality_title
            if self.template_id.legal_base:
                self.legal_base = self.template_id.legal_base
            if self.template_id.default_objective_cause and not self.objective_cause:
                self.objective_cause = self.template_id.default_objective_cause
            if self.template_id.contract_type:
                self.contract_type = self.template_id.contract_type

    def _default_name(self):
        return "Nuevo contrato"

    # ==========================
    # Acciones de Estado (Transición de Ciclo de Vida)
    # ==========================

    def action_set_open(self):
        """Pasa el contrato a estado Vigente."""
        self.write({"state": "open"})

    def action_set_closed(self):
        """Pasa el contrato a estado Finalizado."""
        self.write({"state": "closed"})

    def action_set_cancel(self):
        """Cancela el contrato."""
        self.write({"state": "cancel"})

    def action_set_draft(self):
        """Regresa el contrato a estado Borrador."""
        self.write({"state": "draft"})

    # ==========================
    # Validaciones
    # ==========================

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for contract in self:
            if (
                contract.date_start
                and contract.date_end
                and contract.date_end < contract.date_start
            ):
                raise ValidationError(
                    _("La fecha de fin no puede ser anterior a la fecha de inicio.")
                )

    @api.constrains("wage")
    def _check_wage(self):
        for contract in self:
            if contract.wage is not None and contract.wage < 0:
                raise ValidationError(_("El sueldo no puede ser negativo."))

    @api.constrains("employee_id", "date_start", "date_end", "state")
    def _check_no_overlap(self):
        for contract in self:
            if contract.state not in ("open",) or not contract.date_start:
                continue
            domain = [
                ("employee_id", "=", contract.employee_id.id),
                ("state", "=", "open"),
                ("id", "!=", contract.id),
            ]
            overlapping = self.env["mype.hr.contract"].search(domain)
            for other in overlapping:
                if contract._periods_overlap(other):
                    raise ValidationError(
                        _("El empleado ya tiene un contrato vigente en ese periodo.")
                    )

    def _periods_overlap(self, other):
        self_from = self.date_start or fields.Date.today()
        self_to = self.date_end or fields.Date.max
        other_from = other.date_start or fields.Date.today()
        other_to = other.date_end or fields.Date.max
        return self_from <= other_to and other_from <= self_to

    # ==========================
    # Métodos de Generación de Contrato (Word & PDF)
    # ==========================

    def _format_date_legal(self, d):
        if not d:
            return ""
        months = [
            "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
        ]
        return f"{d.day:02d} de {months[d.month - 1]} del {d.year}"

    def _get_contract_context(self):
        """Genera el diccionario de datos para combinar con plantillas docxtpl o QWeb."""
        self.ensure_one()
        emp = self.employee_id
        company = self.company_id

        # Tratamiento y género basado en hr.employee.sex (Pestaña Información Personal)
        emp_sex = getattr(emp, "sex", None) or getattr(emp, "gender", None)
        if emp_sex == "female":
            employee_treatment = "la señorita"
            employee_party_label = "LA TRABAJADORA"
            employee_gender_label = "Trabajadora"
            employee_qualified_text = "una profesional calificada"
            employee_apt_text = "apta"
            employee_subject_text = "sujeta"
        elif emp_sex == "male":
            employee_treatment = "el señor"
            employee_party_label = "EL TRABAJADOR"
            employee_gender_label = "Trabajador"
            employee_qualified_text = "un profesional calificado"
            employee_apt_text = "apto"
            employee_subject_text = "sujeto"
        else:
            # Si no han seleccionado aún el campo sexo, inferir según primer nombre
            first_name = (emp.name or "").strip().split()[0].lower()
            female_endings = ("a", "ia", "ya", "na", "ra", "sa", "ta", "la", "ma", "da", "za", "eth", "ith", "el")
            male_exceptions = ("jorge", "jose", "pepe", "luis", "carlos", "juan", "david", "raul", "cesar", "oscar", "edgar", "christian", "victor", "manuel", "miguel", "angel")
            if any(first_name.endswith(end) for end in female_endings) and first_name not in male_exceptions:
                employee_treatment = "la señorita"
                employee_party_label = "LA TRABAJADORA"
                employee_gender_label = "Trabajadora"
                employee_qualified_text = "una profesional calificada"
                employee_apt_text = "apta"
                employee_subject_text = "sujeta"
            else:
                employee_treatment = "el señor"
                employee_party_label = "EL TRABAJADOR"
                employee_gender_label = "Trabajador"
                employee_qualified_text = "un profesional calificado"
                employee_apt_text = "apto"
                employee_subject_text = "sujeto"

        # Horario y turnos
        schedule_details = "Lunes a Viernes: De 08:00 am a 06:00 pm | Sábados: De 08:00 am a 11:00 am"
        schedule_summary = "L-V 8am-6pm / Sáb 8am-11am"
        weekly_hours_text = "cuarenta y ocho (48) horas semanales"
        lunch_minutes = "60 minutos"
        if self.schedule_id:
            schedule_summary = self.schedule_id.name or schedule_summary
            if hasattr(self.schedule_id, "weekly_hours") and self.schedule_id.weekly_hours:
                weekly_hours_text = f"{int(self.schedule_id.weekly_hours)} horas semanales"
            if hasattr(self.schedule_id, "shift_line_ids") and self.schedule_id.shift_line_ids:
                lines_txt = []
                days_map = {
                    "0": "Lunes", "1": "Martes", "2": "Miércoles",
                    "3": "Jueves", "4": "Viernes", "5": "Sábado", "6": "Domingo"
                }
                for line in self.schedule_id.shift_line_ids:
                    day_name = days_map.get(str(line.dayofweek), "")
                    lines_txt.append(f"{day_name}: {line.hour_from:02.0f}:00 a {line.hour_to:02.0f}:00")
                if lines_txt:
                    schedule_details = " | ".join(lines_txt)

        # Funciones del puesto (con viñetas limpias automáticas y alineación izquierda)
        raw_functions = (self.job_functions_custom or "").strip()
        if not raw_functions and self.job_id and getattr(self.job_id, "description", None):
            raw_functions = (self.job_id.description or "").strip()
        if not raw_functions:
            raw_functions = (
                "Apoyar en la gestión documental y archivo contable.\n"
                "Analizar cuentas y coordinar entregas de información.\n"
                "Registrar transacciones en el sistema ERP.\n"
                "Colaborar en la preparación de planillas y obligaciones tributarias."
            )

        bullet_lines = []
        for line in raw_functions.split("\n"):
            line_str = line.strip()
            if not line_str:
                continue
            if not line_str.startswith(("•", "-", "*", "1", "2", "3", "4", "5", "6", "7", "8", "9", "a)", "b)", "c)", "d)")):
                line_str = f"•  {line_str}"
            elif line_str.startswith(("- ", "* ")):
                line_str = f"•  {line_str[2:]}"
            bullet_lines.append(line_str)
        functions_bullets = "\n".join(bullet_lines)

        # Modalidad de trabajo
        work_modality_labels = {"presencial": "Presencial", "remoto": "Remoto", "hibrido": "Híbrido"}
        work_modality_txt = work_modality_labels.get(self.work_modality, "Presencial")

        # Periodo de prueba
        trial_txt = f"{self.trial_period_months} meses" if self.trial_period_months else "tres (3) meses"

        # Causa objetiva
        cause_txt = self.objective_cause or (
            "La empresa requiere incorporar personal idóneo que brinde soporte técnico-operativo inmediato "
            "en el procesamiento de las operaciones y la cobertura de los servicios externalizados que demanda el negocio."
        )

        # Domicilio seguro del empleado
        employee_street = (
            getattr(emp, "private_street", None)
            or (getattr(emp, "work_contact_id", None) and emp.work_contact_id.street)
            or (getattr(emp, "user_id", None) and getattr(emp.user_id, "partner_id", None) and emp.user_id.partner_id.street)
            or "Domicilio registrado"
        )

        return {
            "company_name": company.name or "XCB ASOCIADOS S.A.C",
            "company_vat": company.vat or "20616091051",
            "company_street": company.street or "Av. Cerro Grande N° 192, Urb. San Ignacio de Monterrico, Surco, Lima",
            "company_rep_name": getattr(company, "legal_representative_name", None) or "Milagritos Valqui Tello",
            "company_rep_job": getattr(company, "legal_representative_job", None) or "Gerente General",
            "company_rep_vat": getattr(company, "legal_representative_vat", None) or "74616670",
            "company_registry_entry": getattr(company, "company_registry_entry", None) or "16243576",
            "company_remype": getattr(company, "company_remype_number", None) or "0002391655-2026",
            "company_activity_description": getattr(company, "company_activity_description", None) or "consultoría, asesoría y outsourcing contable, tributario, financiero, laboral y legal corporativo",
            "employee_treatment": employee_treatment,
            "employee_party_label": employee_party_label,
            "employee_gender_label": employee_gender_label,
            "employee_qualified_text": employee_qualified_text,
            "employee_apt_text": employee_apt_text,
            "employee_subject_text": employee_subject_text,
            "employee_name": emp.name or "",
            "employee_vat": getattr(emp, "identification_id", None) or "",
            "employee_street": employee_street,
            "job_name": self.job_id.name if self.job_id else "Colaborador",
            "contract_modality_title": self.legal_modality or "Inicio de Nueva Actividad",
            "contract_legal_base": self.legal_base or "artículo 57 del Texto Único Ordenado del Decreto Legislativo N° 728",
            "contract_objective_cause": cause_txt,
            "job_functions_bullets": functions_bullets,
            "duration_text": self.duration_text or "doce (12) meses",
            "date_start_text": self._format_date_legal(self.date_start),
            "date_end_text": self._format_date_legal(self.date_end) if self.date_end else "Indeterminado",
            "trial_period_text": trial_txt,
            "weekly_hours_text": weekly_hours_text,
            "work_modality": work_modality_txt,
            "schedule_details": schedule_details,
            "schedule_summary": schedule_summary,
            "lunch_minutes": lunch_minutes,
            "wage_amount": f"{self.currency_id.symbol or 'S/'} {self.wage:,.2f}",
            "wage_in_words": self.wage_in_words or number_to_words_es(self.wage),
            "wage_frequency": "mensual",
            "labor_regime": "Régimen MYPE / Actividad Privada",
            "signing_city": self.signing_city or "Lima",
            "signing_date_text": f"a los {self.signing_date.day:02d} días del mes de {self._format_date_legal(self.signing_date).split(' de ')[1]}",
        }

    def _render_contract_docx_bytes(self):
        """Combina la plantilla Word con los datos del contrato y devuelve los bytes del .docx."""
        self.ensure_one()
        if not DocxTemplate:
            raise UserError(_("La librería 'docxtpl' no está instalada en el servidor."))

        template_bytes = None
        if self.template_id and self.template_id.file_template:
            template_bytes = base64.b64decode(self.template_id.file_template)
        else:
            default_template = self.env["mype.hr.contract.template"].search([
                ("company_id", "in", [self.company_id.id, False]),
                ("active", "=", True),
            ], limit=1)
            if default_template and default_template.file_template:
                template_bytes = base64.b64decode(default_template.file_template)
            else:
                base_file_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                    "fuentes",
                    "plantilla_contrato_trabajo_mype.docx",
                )
                if os.path.exists(base_file_path):
                    with open(base_file_path, "rb") as f:
                        template_bytes = f.read()

        if not template_bytes:
            raise UserError(_("Por favor seleccione una plantilla Word en el contrato o suba una en Contratos > Plantillas."))

        doc = DocxTemplate(io.BytesIO(template_bytes))
        context = self._get_contract_context()

        # Inserción del Logo oficial de la Empresa (Colores originales 100%, sin marco, superior izquierda)
        logo_data = self.company_id.company_contract_logo or self.company_id.logo
        if logo_data:
            try:
                if isinstance(logo_data, str):
                    raw_logo = base64.b64decode(logo_data)
                elif isinstance(logo_data, bytes):
                    try:
                        raw_logo = base64.b64decode(logo_data)
                    except Exception:
                        raw_logo = logo_data
                else:
                    raw_logo = logo_data
                context["company_logo"] = InlineImage(doc, io.BytesIO(raw_logo), width=docx.shared.Inches(0.75), height=docx.shared.Inches(0.75))
            except Exception:
                context["company_logo"] = ""
        else:
            context["company_logo"] = ""

        doc.render(context)

        output_stream = io.BytesIO()
        doc.save(output_stream)
        return output_stream.getvalue()

    def _generate_pdf_from_docx(self, docx_bytes=None):
        """Convierte los bytes del Word (.docx) a PDF idéntico usando Microsoft Word si está disponible en Windows."""
        if not win32com:
            return None

        if not docx_bytes:
            docx_bytes = self._render_contract_docx_bytes()

        temp_dir = tempfile.gettempdir()
        temp_docx = os.path.join(temp_dir, f"contract_{self.id}_{os.getpid()}.docx")
        temp_pdf = os.path.join(temp_dir, f"contract_{self.id}_{os.getpid()}.pdf")

        try:
            with open(temp_docx, "wb") as f:
                f.write(docx_bytes)

            pythoncom.CoInitialize()
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            doc = word.Documents.Open(os.path.abspath(temp_docx))
            doc.SaveAs(os.path.abspath(temp_pdf), FileFormat=17) # 17 = wdFormatPDF
            doc.Close(False)
            word.Quit()

            with open(temp_pdf, "rb") as f:
                pdf_bytes = f.read()

            return pdf_bytes
        except Exception:
            return None
        finally:
            try: pythoncom.CoUninitialize()
            except: pass
            if os.path.exists(temp_docx):
                try: os.remove(temp_docx)
                except: pass
            if os.path.exists(temp_pdf):
                try: os.remove(temp_pdf)
                except: pass

    def action_generate_contract_docx(self):
        """Genera el archivo Word (.docx) combinando los datos con la plantilla docxtpl."""
        self.ensure_one()
        docx_data = self._render_contract_docx_bytes()
        file_name = f"Contrato_{self.employee_id.name.replace(' ', '_')}_{self.legal_modality.replace(' ', '_')}.docx"
        attachment = self.env["ir.attachment"].create({
            "name": file_name,
            "type": "binary",
            "datas": base64.b64encode(docx_data),
            "res_model": self._name,
            "res_id": self.id,
            "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        })

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    def action_print_contract_pdf(self):
        """Genera e imprime el reporte de Contrato Laboral en formato PDF idéntico al Word."""
        self.ensure_one()
        # 1. Intentar conversión de alta fidelidad desde Word (.docx -> .pdf)
        pdf_data = self._generate_pdf_from_docx()
        if pdf_data:
            file_name = f"Contrato_{self.employee_id.name.replace(' ', '_')}_{self.legal_modality.replace(' ', '_')}.pdf"
            attachment = self.env["ir.attachment"].create({
                "name": file_name,
                "type": "binary",
                "datas": base64.b64encode(pdf_data),
                "res_model": self._name,
                "res_id": self.id,
                "mimetype": "application/pdf",
            })
            return {
                "type": "ir.actions.act_url",
                "url": f"/web/content/{attachment.id}?download=true",
                "target": "self",
            }

        # 2. Fallback a reporte QWeb PDF
        return self.env.ref("mype_hr_core.action_report_mype_contract_pdf").report_action(self)

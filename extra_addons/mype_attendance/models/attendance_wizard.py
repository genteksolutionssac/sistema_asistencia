# -*- coding: utf-8 -*-
import base64
import calendar
import io
from datetime import datetime, date, timedelta
import pytz

from odoo import models, fields, api, _
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class MypeAttendanceReportWizard(models.TransientModel):
    _name = "mype.attendance.report.wizard"
    _description = "Asistente de Reporte y Exportación de Asistencias"

    def _default_year(self):
        return str(fields.Date.today().year)

    def _default_month(self):
        return str(fields.Date.today().month)

    year = fields.Selection(
        [
            ("2024", "2024"),
            ("2025", "2025"),
            ("2026", "2026"),
            ("2027", "2027"),
            ("2028", "2028"),
            ("2029", "2029"),
            ("2030", "2030"),
        ],
        string="Año",
        default=_default_year,
        required=True,
    )

    month = fields.Selection(
        [
            ("1", "Enero"),
            ("2", "Febrero"),
            ("3", "Marzo"),
            ("4", "Abril"),
            ("5", "Mayo"),
            ("6", "Junio"),
            ("7", "Julio"),
            ("8", "Agosto"),
            ("9", "Septiembre"),
            ("10", "Octubre"),
            ("11", "Noviembre"),
            ("12", "Diciembre"),
        ],
        string="Mes",
        default=_default_month,
        required=True,
    )

    filter_type = fields.Selection(
        [
            ("all", "Toda la Empresa"),
            ("by_department", "Por Área / Departamento"),
            ("by_manager", "Por Persona a Cargo (Responsable del Área)"),
            ("by_employee", "Por Colaboradores Específicos"),
        ],
        string="Tipo de Filtro",
        default="all",
        required=True,
    )

    department_id = fields.Many2one(
        "hr.department",
        string="Área / Departamento",
    )

    manager_id = fields.Many2one(
        "hr.employee",
        string="Responsable del Área",
        help="Seleccione al personal a cargo para incluir sus asistencias y las de su equipo.",
    )

    include_manager = fields.Boolean(
        string="Incluir al Responsable en el reporte",
        default=True,
        help="Si está marcado, incluirá tanto las marcaciones del responsable como las de sus colaboradores a cargo.",
    )

    employee_ids = fields.Many2many(
        "hr.employee",
        string="Colaboradores",
    )

    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        default=lambda self: self.env.company,
        required=True,
    )

    # Campos para descarga de archivo
    excel_file = fields.Binary(
        string="Archivo Excel",
        readonly=True,
    )
    excel_filename = fields.Char(
        string="Nombre del archivo",
        readonly=True,
    )

    def _get_date_range(self):
        """Devuelve (date_start, date_end) del mes y año seleccionados."""
        self.ensure_one()
        y = int(self.year)
        m = int(self.month)
        last_day = calendar.monthrange(y, m)[1]
        return date(y, m, 1), date(y, m, last_day)

    def _get_target_employees(self):
        """Calcula el listado de empleados según el filtro seleccionado."""
        self.ensure_one()
        emp_model = self.env["hr.employee"]

        if self.filter_type == "by_department":
            if not self.department_id:
                raise UserError(_("Debe seleccionar un Área / Departamento."))
            return emp_model.search([("department_id", "=", self.department_id.id)])

        elif self.filter_type == "by_manager":
            if not self.manager_id:
                raise UserError(_("Debe seleccionar a la persona a cargo / responsable."))
            subordinates = emp_model.search([("parent_id", "=", self.manager_id.id)])
            if self.include_manager:
                return (subordinates | self.manager_id)
            return subordinates

        elif self.filter_type == "by_employee":
            if not self.employee_ids:
                raise UserError(_("Debe seleccionar al menos un colaborador."))
            return self.employee_ids

        return emp_model.search([("company_id", "=", self.company_id.id)])

    def action_view_attendances(self):
        """Abre la vista de registros de asistencia con el dominio filtrado."""
        self.ensure_one()
        date_start, date_end = self._get_date_range()
        employees = self._get_target_employees()

        domain = [
            ("date", ">=", date_start),
            ("date", "<=", date_end),
            ("employee_id", "in", employees.ids),
        ]

        action = self.env.ref("mype_attendance.action_mype_attendance").read()[0]
        action["domain"] = domain
        action["context"] = {
            "search_default_group_employee": 1,
            "default_company_id": self.company_id.id,
        }
        return action

    def action_export_excel(self):
        """Genera y descarga un reporte Excel (.xlsx) con los datos de asistencia del mes."""
        self.ensure_one()
        if not xlsxwriter:
            raise UserError(_("La librería xlsxwriter no está instalada en el sistema."))

        date_start, date_end = self._get_date_range()
        employees = self._get_target_employees()

        attendances = self.env["mype.attendance"].search([
            ("date", ">=", date_start),
            ("date", "<=", date_end),
            ("employee_id", "in", employees.ids),
        ], order="employee_id, date")

        month_name = dict(self._fields["month"].selection).get(self.month, "")
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        worksheet = workbook.add_worksheet("Detalle Diario")

        # Estilos
        title_fmt = workbook.add_format({
            "bold": True, "font_size": 16, "font_color": "#1F497D", "align": "left",
        })
        subtitle_fmt = workbook.add_format({
            "italic": True, "font_size": 10, "font_color": "#595959",
        })
        header_fmt = workbook.add_format({
            "bold": True, "font_size": 10, "bg_color": "#1F497D", "font_color": "#FFFFFF",
            "align": "center", "valign": "vcenter", "border": 1,
        })
        cell_fmt = workbook.add_format({"font_size": 9, "border": 1, "valign": "vcenter"})
        cell_center = workbook.add_format({"font_size": 9, "border": 1, "align": "center", "valign": "vcenter"})
        cell_late = workbook.add_format({
            "font_size": 9, "border": 1, "align": "center", "valign": "vcenter",
            "bg_color": "#FCE4D6", "font_color": "#C00000", "bold": True,
        })
        cell_num = workbook.add_format({"font_size": 9, "border": 1, "align": "right", "valign": "vcenter", "num_format": "0.00"})

        # Título
        worksheet.write(0, 0, "REPORTE CONSOLIDADO DE ASISTENCIAS", title_fmt)
        filtro_str = f"Periodo: {month_name} {self.year} | Compañía: {self.company_id.name}"
        if self.filter_type == "by_department" and self.department_id:
            filtro_str += f" | Área: {self.department_id.name}"
        elif self.filter_type == "by_manager" and self.manager_id:
            filtro_str += f" | A cargo de: {self.manager_id.name}"
        worksheet.write(1, 0, filtro_str, subtitle_fmt)

        # Encabezados
        headers = [
            "Fecha", "Código", "Colaborador", "Área / Departamento", "Responsable a Cargo",
            "Horario / Turno", "Entrada Prog.", "Entrada Marcada", "Salida Prog.", "Salida Marcada",
            "Horas Trabajadas", "Tardanza (min)", "Salida Anticip. (min)", "Horas Extras (min)", "Estado"
        ]
        worksheet.set_row(3, 24)
        for col_idx, h in enumerate(headers):
            worksheet.write(3, col_idx, h, header_fmt)

        user_tz = pytz.timezone(self.env.user.tz or self.env.company.partner_id.tz or "America/Lima")
        def fmt_time(t):
            if not t:
                return "-"
            if hasattr(t, "strftime"):
                if hasattr(t, "tzinfo") and t.tzinfo is None:
                    utc_dt = pytz.utc.localize(t)
                    local_dt = utc_dt.astimezone(user_tz)
                    return local_dt.strftime("%H:%M")
                return t.strftime("%H:%M")
            if isinstance(t, (int, float)):
                return f"{int(t):02d}:{int(round((t - int(t)) * 60)):02d}"
            return str(t)

        row = 4
        for att in attendances:
            worksheet.write(row, 0, str(att.date), cell_center)
            worksheet.write(row, 1, att.employee_code or "-", cell_center)
            worksheet.write(row, 2, att.employee_id.name or "", cell_fmt)
            worksheet.write(row, 3, att.department_id.name or "-", cell_fmt)
            worksheet.write(row, 4, att.manager_id.name or "-", cell_fmt)
            worksheet.write(row, 5, att.shift_id.name or "-", cell_fmt)
            worksheet.write(row, 6, fmt_time(att.scheduled_entry), cell_center)
            worksheet.write(row, 7, fmt_time(att.entry_time), cell_center)
            worksheet.write(row, 8, fmt_time(att.scheduled_exit), cell_center)
            worksheet.write(row, 9, fmt_time(att.exit_time), cell_center)
            worksheet.write(row, 10, att.worked_hours or 0.0, cell_num)
            
            # Tardanza con color
            if att.is_late and att.late_minutes > 0:
                worksheet.write(row, 11, round(att.late_minutes, 1), cell_late)
            else:
                worksheet.write(row, 11, 0.0, cell_center)

            worksheet.write(row, 12, round(att.early_exit_minutes or 0.0, 1), cell_center)
            worksheet.write(row, 13, round(att.overtime_minutes or 0.0, 1), cell_center)
            worksheet.write(row, 14, dict(att._fields["state"].selection).get(att.state, att.state), cell_center)
            row += 1

        # Autoajuste de columnas
        col_widths = [12, 10, 28, 20, 22, 18, 14, 14, 14, 14, 15, 15, 16, 16, 12]
        for idx, w in enumerate(col_widths):
            worksheet.set_column(idx, idx, w)

        # ==========================================
        # Hoja 2: Resumen Consolidado por Colaborador
        # ==========================================
        summary_sheet = workbook.add_worksheet("Resumen por Colaborador")

        total_fmt = workbook.add_format({
            "bold": True, "font_size": 10, "bg_color": "#D9E1F2", "border": 1, "align": "right", "valign": "vcenter", "num_format": "0.00",
        })
        total_int_fmt = workbook.add_format({
            "bold": True, "font_size": 10, "bg_color": "#D9E1F2", "border": 1, "align": "center", "valign": "vcenter",
        })
        total_label_fmt = workbook.add_format({
            "bold": True, "font_size": 10, "bg_color": "#D9E1F2", "border": 1, "align": "left", "valign": "vcenter",
        })

        summary_sheet.write(0, 0, "RESUMEN CONSOLIDADO POR COLABORADOR", title_fmt)
        summary_sheet.write(1, 0, filtro_str, subtitle_fmt)

        sum_headers = [
            "Código", "Colaborador", "Área / Departamento", "Cargo", "Horario Asignado",
            "Días Programados", "Días Asistidos", "Días No Laborados",
            "Minutos Tardanza", "Salida Anticip. (min)", "Horas Extras (min)", "Total Horas Trabajadas"
        ]
        summary_sheet.set_row(3, 24)
        for col_idx, h in enumerate(sum_headers):
            summary_sheet.write(3, col_idx, h, header_fmt)

        s_row = 4
        tot_prog_sum = 0
        tot_asist_sum = 0
        tot_no_lab_sum = 0
        tot_late_sum = 0.0
        tot_early_sum = 0.0
        tot_ot_sum = 0.0
        tot_hrs_sum = 0.0

        for emp in employees:
            shift = emp.effective_shift_id if hasattr(emp, "effective_shift_id") and emp.effective_shift_id else emp.company_id.default_shift_id
            working_dows = set()
            if shift:
                working_dows = set(line.day_of_week for line in shift.line_ids if line.is_working_day)

            dias_programados = 0
            cur_day = date_start
            while cur_day <= date_end:
                if str(cur_day.weekday()) in working_dows:
                    dias_programados += 1
                cur_day += timedelta(days=1)

            emp_atts = [a for a in attendances if a.employee_id.id == emp.id]
            dias_asistidos = len([a for a in emp_atts if a.entry_time])
            dias_no_laborados = max(0, dias_programados - dias_asistidos)

            emp_late = sum(a.late_minutes for a in emp_atts if a.is_late and a.late_minutes > 0)
            emp_early = sum(a.early_exit_minutes for a in emp_atts if a.is_early_exit and a.early_exit_minutes > 0)
            emp_ot = sum(a.overtime_minutes for a in emp_atts if a.has_overtime and a.overtime_minutes > 0)
            emp_hours = sum(a.worked_hours or 0.0 for a in emp_atts)

            tot_prog_sum += dias_programados
            tot_asist_sum += dias_asistidos
            tot_no_lab_sum += dias_no_laborados
            tot_late_sum += emp_late
            tot_early_sum += emp_early
            tot_ot_sum += emp_ot
            tot_hrs_sum += emp_hours

            summary_sheet.write(s_row, 0, emp.employee_code or "-", cell_center)
            summary_sheet.write(s_row, 1, emp.name or "", cell_fmt)
            summary_sheet.write(s_row, 2, emp.department_id.name or "-", cell_fmt)
            summary_sheet.write(s_row, 3, emp.job_id.name or "-", cell_fmt)
            summary_sheet.write(s_row, 4, shift.name if shift else "-", cell_fmt)
            summary_sheet.write(s_row, 5, dias_programados, cell_center)
            summary_sheet.write(s_row, 6, dias_asistidos, cell_center)

            if dias_no_laborados > 0:
                summary_sheet.write(s_row, 7, dias_no_laborados, cell_late)
            else:
                summary_sheet.write(s_row, 7, 0, cell_center)

            if emp_late > 0:
                summary_sheet.write(s_row, 8, round(emp_late, 1), cell_late)
            else:
                summary_sheet.write(s_row, 8, 0.0, cell_center)

            if emp_early > 0:
                summary_sheet.write(s_row, 9, round(emp_early, 1), cell_late)
            else:
                summary_sheet.write(s_row, 9, 0.0, cell_center)

            summary_sheet.write(s_row, 10, round(emp_ot, 1), cell_center)
            summary_sheet.write(s_row, 11, round(emp_hours, 2), cell_num)
            s_row += 1

        # Fila de Totales Generales
        summary_sheet.write(s_row, 0, "", total_label_fmt)
        summary_sheet.write(s_row, 1, "TOTALES GENERALES", total_label_fmt)
        summary_sheet.write(s_row, 2, "", total_label_fmt)
        summary_sheet.write(s_row, 3, "", total_label_fmt)
        summary_sheet.write(s_row, 4, "", total_label_fmt)
        summary_sheet.write(s_row, 5, tot_prog_sum, total_int_fmt)
        summary_sheet.write(s_row, 6, tot_asist_sum, total_int_fmt)
        summary_sheet.write(s_row, 7, tot_no_lab_sum, total_int_fmt)
        summary_sheet.write(s_row, 8, round(tot_late_sum, 1), total_fmt)
        summary_sheet.write(s_row, 9, round(tot_early_sum, 1), total_fmt)
        summary_sheet.write(s_row, 10, round(tot_ot_sum, 1), total_fmt)
        summary_sheet.write(s_row, 11, round(tot_hrs_sum, 2), total_fmt)

        sum_widths = [12, 28, 22, 20, 20, 16, 15, 16, 16, 18, 16, 20]
        for idx, w in enumerate(sum_widths):
            summary_sheet.set_column(idx, idx, w)

        workbook.close()
        output.seek(0)
        file_base64 = base64.b64encode(output.read())
        output.close()

        filename = f"Asistencias_{month_name}_{self.year}.xlsx"
        self.write({
            "excel_file": file_base64,
            "excel_filename": filename,
        })

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content?model=mype.attendance.report.wizard&id={self.id}&field=excel_file&download=true&filename={filename}",
            "target": "self",
        }
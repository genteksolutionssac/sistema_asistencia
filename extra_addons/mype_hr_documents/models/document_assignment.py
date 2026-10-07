# -*- coding: utf-8 -*-
import base64
import hashlib
import pytz
from datetime import datetime
from odoo import models, fields, api
from odoo.exceptions import UserError


class MypeHrDocumentAssignment(models.Model):
    _name = "mype.hr.document.assignment"
    _description = "Documento Laboral Asignado a Colaborador"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    batch_id = fields.Many2one(
        "mype.hr.document.batch",
        string="Lote / Emisión",
        required=True,
        ondelete="cascade",
        index=True,
    )
    template_id = fields.Many2one(
        "mype.hr.document.template",
        string="Plantilla",
        related="batch_id.template_id",
        store=True,
        index=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Colaborador",
        required=True,
        ondelete="restrict",
        index=True,
    )
    department_id = fields.Many2one(
        "hr.department",
        string="Departamento / Área",
        related="employee_id.department_id",
        store=True,
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        related="batch_id.company_id",
        store=True,
    )
    date_issued = fields.Date(
        string="Fecha de Emisión",
        related="batch_id.date_issued",
        store=True,
    )
    state = fields.Selection(
        [
            ("pending", "Pendiente de Firma"),
            ("signed", "Firmado"),
        ],
        string="Estado",
        default="pending",
        tracking=True,
        index=True,
    )
    date_signed = fields.Datetime(
        string="Fecha y Hora de Firma",
        tracking=True,
        copy=False,
    )
    date_signed_local = fields.Char(
        string="Fecha Local de Firma",
        compute="_compute_date_signed_local",
    )
    employee_signature = fields.Binary(
        string="Firma del Colaborador",
        copy=False,
        attachment=True,
    )
    client_ip = fields.Char(
        string="Dirección IP",
        copy=False,
    )
    user_agent = fields.Char(
        string="Dispositivo / Navegador",
        copy=False,
    )
    audit_hash = fields.Char(
        string="Huella Digital (Hash SHA-256)",
        copy=False,
        help="Código criptográfico que garantiza que el documento no fue alterado tras la firma.",
    )
    pdf_signed = fields.Binary(
        string="PDF Firmado",
        copy=False,
        attachment=True,
    )
    pdf_signed_filename = fields.Char(
        string="Nombre del Archivo PDF",
        compute="_compute_pdf_filename",
        store=True,
    )

    _batch_emp_uniq = models.Constraint(
        "UNIQUE(batch_id, employee_id)",
        "El colaborador ya tiene asignado este documento.",
    )

    @api.depends("template_id.name", "employee_id.name")
    def _compute_pdf_filename(self):
        for rec in self:
            emp_name = (rec.employee_id.name or "colaborador").replace(" ", "_")
            doc_name = (rec.template_id.name or "documento").replace(" ", "_")
            rec.pdf_signed_filename = f"{doc_name}_{emp_name}.pdf"

    def _format_local_datetime(self, dt):
        if not dt:
            return ""
        try:
            local_tz = pytz.timezone("America/Lima")
            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt)
            return dt.astimezone(local_tz).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return dt.strftime("%Y-%m-%d %H:%M:%S")

    @api.depends("date_signed")
    def _compute_date_signed_local(self):
        for rec in self:
            rec.date_signed_local = self._format_local_datetime(rec.date_signed)

    def _get_document_context(self):
        """Retorna el diccionario de variables dinámicas para la plantilla QWeb A4."""
        self.ensure_one()
        emp = self.employee_id
        company = self.company_id or self.env.company

        # Fecha formateada en español
        ref_date = self.date_signed.date() if self.date_signed else (self.date_issued or fields.Date.today())
        meses = [
            "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
        ]
        date_text = f"Lima, {ref_date.day} de {meses[ref_date.month]} de {ref_date.year}"

        employee_name = emp.legal_name or emp.name or ""
        employee_dni = emp.identification_id or ""

        signed_at_text = self._format_local_datetime(self.date_signed) if self.date_signed else ""

        return {
            "company_name": company.name or "ACTITUD GROUP S.A.C.",
            "company_vat": company.vat or "",
            "company_rep_name": company.legal_representative_name or "Gerencia General",
            "company_rep_job": company.legal_representative_job or "Gerente General",
            "company_rep_vat": company.legal_representative_vat or "",
            "company_signature": company.company_signature_image,
            "employee_name": employee_name,
            "employee_dni": employee_dni,
            "employee_job": emp.job_title or (emp.job_id.name if emp.job_id else "Colaborador"),
            "employee_signature": self.employee_signature,
            "date_text": date_text,
            "is_signed": bool(self.state == "signed" and self.employee_signature),
            "signed_at_text": signed_at_text,
            "client_ip": self.client_ip or "",
            "audit_hash": self.audit_hash or "",
        }

    def render_pdf_bytes(self):
        """Renderiza el documento PDF en bytes usando la acción de reporte QWeb oficial."""
        self.ensure_one()
        report_action = self.env.ref("mype_hr_documents.action_report_authorization_image_pdf")
        pdf_content, _ = report_action._render_qweb_pdf(report_action.id, res_ids=[self.id])
        return pdf_content

    def register_signature(self, signature_b64, client_ip=None, user_agent=None):
        """Registra la firma del colaborador, sella la auditoría y genera el PDF definitivo."""
        self.ensure_one()
        if not signature_b64:
            raise UserError("No se ha proporcionado la firma digital del colaborador.")

        # Limpiar prefijo data:image/png;base64, si viene incluido
        if "," in signature_b64:
            signature_b64 = signature_b64.split(",", 1)[1]
        signature_b64 = str(signature_b64).strip().replace("\n", "").replace("\r", "")

        sig_bytes = base64.b64decode(signature_b64)
        now = fields.Datetime.now()

        # Guardar la firma en el perfil del empleado si no tenía una
        if not self.employee_id.digital_signature:
            self.employee_id.sudo().write({"digital_signature": signature_b64})

        # Generar hash preliminar de auditoría
        audit_raw = f"{self.id}-{self.employee_id.id}-{now.isoformat()}-{client_ip or ''}"
        audit_hash = hashlib.sha256(audit_raw.encode("utf-8")).hexdigest()

        self.write({
            "state": "signed",
            "date_signed": now,
            "employee_signature": signature_b64,
            "client_ip": client_ip or "",
            "user_agent": user_agent or "",
            "audit_hash": audit_hash,
        })

        # Generar y archivar el PDF final firmado
        pdf_bytes = self.render_pdf_bytes()
        final_hash = hashlib.sha256(pdf_bytes).hexdigest()

        self.write({
            "pdf_signed": base64.b64encode(pdf_bytes),
            "audit_hash": final_hash,
        })

        self.message_post(
            body=f"Documento firmado electrónicamente por {self.employee_id.name} el {self.date_signed_local}.",
            subtype_xmlid="mail.mt_note",
        )
        return True

    def action_download_pdf(self):
        """Permite a la administradora descargar o visualizar el documento desde Odoo."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{self._name}/{self.id}/pdf_signed/{self.pdf_signed_filename}?download=true",
            "target": "new",
        }

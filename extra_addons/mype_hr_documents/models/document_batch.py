# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class MypeHrDocumentBatch(models.Model):
    _name = "mype.hr.document.batch"
    _description = "Emisión Masiva de Documentos RRHH"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(
        string="Título de la Emisión",
        required=True,
        tracking=True,
    )
    template_id = fields.Many2one(
        "mype.hr.document.template",
        string="Plantilla de Documento",
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )
    date_issued = fields.Date(
        string="Fecha de Emisión",
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    target_type = fields.Selection(
        [
            ("all", "Todos los Colaboradores"),
            ("department", "Por Departamento / Área"),
            ("employee", "Colaboradores Específicos"),
        ],
        string="Destinatarios",
        default="all",
        required=True,
        tracking=True,
    )
    department_ids = fields.Many2many(
        "hr.department",
        "mype_doc_batch_dept_rel",
        "batch_id",
        "department_id",
        string="Departamentos Seleccionados",
    )
    employee_ids = fields.Many2many(
        "hr.employee",
        "mype_doc_batch_emp_rel",
        "batch_id",
        "employee_id",
        string="Colaboradores Seleccionados",
    )
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("sent", "Emitido / En Proceso"),
            ("done", "Completado"),
            ("cancel", "Cancelado"),
        ],
        string="Estado",
        default="draft",
        tracking=True,
    )
    assignment_ids = fields.One2many(
        "mype.hr.document.assignment",
        "batch_id",
        string="Documentos por Colaborador",
    )

    total_assigned = fields.Integer(
        string="Total Asignados",
        compute="_compute_metrics",
        store=True,
    )
    total_signed = fields.Integer(
        string="Total Firmados",
        compute="_compute_metrics",
        store=True,
    )
    total_pending = fields.Integer(
        string="Total Pendientes",
        compute="_compute_metrics",
        store=True,
    )
    progress_percent = fields.Float(
        string="Avance (%)",
        compute="_compute_metrics",
        store=True,
    )

    @api.depends("assignment_ids.state")
    def _compute_metrics(self):
        for batch in self:
            assignments = batch.assignment_ids
            total = len(assignments)
            signed = sum(1 for a in assignments if a.state == "signed")
            pending = total - signed
            batch.total_assigned = total
            batch.total_signed = signed
            batch.total_pending = pending
            batch.progress_percent = (signed / total * 100.0) if total > 0 else 0.0

            if batch.state == "sent" and total > 0 and pending == 0:
                batch.state = "done"

    def action_send_to_employees(self):
        """Genera y emite los documentos personalizados para cada colaborador seleccionado."""
        self.ensure_one()
        if not self.template_id:
            raise UserError("Debe seleccionar una plantilla de documento.")

        emp_model = self.env["hr.employee"]
        domain = [("company_id", "=", self.company_id.id), ("active", "=", True)]

        if self.target_type == "all":
            employees = emp_model.search(domain)
        elif self.target_type == "department":
            if not self.department_ids:
                raise UserError("Seleccione al menos un departamento para continuar.")
            employees = emp_model.search(domain + [("department_id", "in", self.department_ids.ids)])
        elif self.target_type == "employee":
            if not self.employee_ids:
                raise UserError("Seleccione al menos un colaborador para continuar.")
            employees = self.employee_ids
        else:
            employees = emp_model.browse([])

        if not employees:
            raise UserError("No se encontraron colaboradores elegibles para los filtros seleccionados.")

        existing_emp_ids = self.assignment_ids.mapped("employee_id.id")
        to_create = []
        for emp in employees:
            if emp.id not in existing_emp_ids:
                to_create.append({
                    "batch_id": self.id,
                    "template_id": self.template_id.id,
                    "employee_id": emp.id,
                    "state": "pending",
                })

        if to_create:
            self.env["mype.hr.document.assignment"].create(to_create)

        self.state = "sent"
        self.message_post(
            body=f"Documento '{self.template_id.name}' emitido a {len(employees)} colaboradores.",
            subtype_xmlid="mail.mt_note",
        )

        # Enviar Notificación Push FCM a los colaboradores
        if "hr.employee.device" in self.env:
            self.env["hr.employee.device"].send_push_to_employees(
                employees=employees,
                title="📄 Documento por Firmar",
                body=f"Se ha emitido '{self.template_id.name}'. Ingresa a firmarlo digitalmente.",
                data={"type": "document", "batch_id": str(self.id)},
                web_link="/",
            )

    def action_remind_pending(self):
        """Prepara el recordatorio a los colaboradores que tienen el documento pendiente."""
        self.ensure_one()
        pending = self.assignment_ids.filtered(lambda a: a.state == "pending")
        if not pending:
            raise UserError("Todos los colaboradores ya han firmado este documento.")

        pending_employees = pending.mapped("employee_id")

        # Notificación Push FCM de recordatorio
        if "hr.employee.device" in self.env:
            self.env["hr.employee.device"].send_push_to_employees(
                employees=pending_employees,
                title="⏰ Recordatorio de Firma",
                body=f"Tienes pendiente firmar '{self.template_id.name}'. Por favor ingresa a completarlo.",
                data={"type": "document", "batch_id": str(self.id)},
                web_link="/",
            )

        names = ", ".join(pending.mapped("employee_id.name")[:5])
        suffix = "..." if len(pending) > 5 else ""
        self.message_post(
            body=f"Se envió recordatorio a {len(pending)} colaboradores pendientes de firma ({names}{suffix}).",
            subtype_xmlid="mail.mt_note",
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Recordatorio Enviado",
                "message": f"Se ha notificado a {len(pending)} colaboradores pendientes de firma.",
                "type": "success",
                "sticky": False,
            },
        }

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

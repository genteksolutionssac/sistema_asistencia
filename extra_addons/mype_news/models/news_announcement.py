# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class MypeNewsAnnouncement(models.Model):
    _name = "mype.news.announcement"
    _description = "Novedades y Comunicados de Personal"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "is_pinned desc, published_date desc, id desc"

    name = fields.Char(
        string="Título del Comunicado",
        required=True,
        tracking=True,
        help="Ej: Aniversario de la Empresa, Feriado Puente, Cumpleaños del Mes",
    )

    category = fields.Selection(
        [
            ("corporate", "📢 Noticia Corporativa"),
            ("birthday", "🎈 Cumpleaños / Aniversario"),
            ("holiday", "📅 Día Festivo / Feriado"),
            ("official", "⚠️ Comunicado Oficial"),
            ("benefits", "🎁 Beneficios / Convenios"),
        ],
        string="Categoría",
        default="corporate",
        required=True,
        tracking=True,
    )

    is_pinned = fields.Boolean(
        string="Fijar al inicio del buzón (Prioritario 📌)",
        default=False,
        tracking=True,
        help="Aparecerá siempre fijado arriba de todos los demás comunicados en la app móvil.",
    )

    description = fields.Text(
        string="Descripción / Mensaje",
        help="Texto explicativo adicional (opcional si la información ya está en la imagen o PDF).",
    )

    file_type = fields.Selection(
        [
            ("none", "Sin archivo adjunto"),
            ("image", "Imagen (Flyer / Afiche)"),
            ("pdf", "Documento PDF (Memorándum / Circular)"),
        ],
        string="Tipo de Archivo",
        default="none",
        required=True,
    )

    image_cover = fields.Binary(
        string="Imagen de Portada",
        attachment=True,
        help="Imagen en formato JPG o PNG visible de forma directa en la app móvil.",
    )

    image_filename = fields.Char(
        string="Nombre del archivo de imagen",
    )

    pdf_file = fields.Binary(
        string="Archivo PDF",
        attachment=True,
        help="Documento PDF que los colaboradores podrán abrir y visualizar en la app.",
    )

    pdf_filename = fields.Char(
        string="Nombre del archivo PDF",
    )

    target_type = fields.Selection(
        [
            ("all", "Todos los colaboradores activos"),
            ("department", "Por Áreas / Departamentos"),
            ("employee", "Colaboradores específicos"),
        ],
        string="Audiencia / Destinatarios",
        default="all",
        required=True,
    )

    department_ids = fields.Many2many(
        "hr.department",
        "mype_news_dept_rel",
        "news_id",
        "dept_id",
        string="Departamentos destinatarios",
    )

    employee_ids = fields.Many2many(
        "hr.employee",
        "mype_news_emp_rel",
        "news_id",
        "emp_id",
        string="Colaboradores específicos",
    )

    schedule_type = fields.Selection(
        [
            ("now", "Enviar de inmediato al confirmar"),
            ("scheduled", "Programar envío automático por fecha y hora"),
        ],
        string="Modalidad de Envío",
        default="now",
        required=True,
    )

    scheduled_date = fields.Datetime(
        string="Fecha y Hora Programada",
        help="Fecha y hora en la que el sistema emitirá automáticamente el comunicado al buzón.",
    )

    published_date = fields.Datetime(
        string="Fecha de Publicación",
        readonly=True,
        copy=False,
        help="Momento exacto en que fue emitido a los colaboradores.",
    )

    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("scheduled", "Programado"),
            ("sent", "Enviado"),
            ("cancelled", "Cancelado"),
        ],
        string="Estado",
        default="draft",
        tracking=True,
        copy=False,
    )

    recipient_ids = fields.One2many(
        "mype.news.recipient",
        "news_id",
        string="Destinatarios y Seguimiento de Lectura",
    )

    total_recipients = fields.Integer(
        string="Total Destinatarios",
        compute="_compute_stats",
        store=True,
    )

    total_read = fields.Integer(
        string="Leídos",
        compute="_compute_stats",
        store=True,
    )

    total_pending = fields.Integer(
        string="Pendientes de Lectura",
        compute="_compute_stats",
        store=True,
    )

    read_percent = fields.Float(
        string="% de Lectura",
        compute="_compute_stats",
        store=True,
    )

    total_reactions = fields.Integer(
        string="Total Reacciones",
        compute="_compute_stats",
        store=True,
    )

    reactions_summary_display = fields.Char(
        string="Resumen de Reacciones",
        compute="_compute_stats",
        store=True,
    )

    @api.depends("recipient_ids", "recipient_ids.is_read", "recipient_ids.reaction")
    def _compute_stats(self):
        emoji_map = {
            "love": "❤️",
            "like": "👍",
            "laugh": "😂",
            "wow": "😮",
            "pray": "🙏",
            "sad": "😢",
        }
        for rec in self:
            total = len(rec.recipient_ids)
            read = sum(1 for r in rec.recipient_ids if r.is_read)
            pending = total - read
            percent = (read / total * 100.0) if total > 0 else 0.0
            rec.total_recipients = total
            rec.total_read = read
            rec.total_pending = pending
            rec.read_percent = round(percent, 1)

            # Estadísticas de reacciones
            reacted_list = [r.reaction for r in rec.recipient_ids if r.reaction]
            rec.total_reactions = len(reacted_list)

            parts = []
            for key in ["love", "like", "laugh", "wow", "pray", "sad"]:
                count = reacted_list.count(key)
                if count > 0:
                    parts.append(f"{emoji_map[key]} {count}")
            rec.reactions_summary_display = "  ·  ".join(parts) if parts else ""

    def get_reactions_breakdown(self):
        """Retorna diccionario de conteos por emoji para consumo en APIs móviles."""
        self.ensure_one()
        counts = {
            "like": 0,
            "love": 0,
            "laugh": 0,
            "wow": 0,
            "sad": 0,
            "pray": 0,
        }
        for r in self.recipient_ids:
            if r.reaction and r.reaction in counts:
                counts[r.reaction] += 1
        return {
            "total": sum(counts.values()),
            "counts": counts,
        }

    def action_send_now(self):
        """Emite el comunicado de inmediato a los destinatarios configurados."""
        for rec in self:
            if rec.file_type == "image" and not rec.image_cover:
                raise ValidationError(_("Debe cargar una imagen o cambiar el tipo de archivo."))
            if rec.file_type == "pdf" and not rec.pdf_file:
                raise ValidationError(_("Debe cargar un documento PDF o cambiar el tipo de archivo."))

            rec._generate_recipients()
            rec.write({
                "state": "sent",
                "published_date": fields.Datetime.now(),
            })
            rec._notify_devices()

    def action_send_all_now(self):
        """Fuerza el envío inmediato a toda la empresa sin importar los filtros previos."""
        self.ensure_one()
        self.write({"target_type": "all"})
        self.action_send_now()

    def action_schedule(self):
        """Pasa el comunicado al estado Programado para que el cron lo publique."""
        for rec in self:
            if not rec.scheduled_date:
                raise ValidationError(_("Debe definir una fecha y hora futura para programar el envío."))
            if rec.scheduled_date <= fields.Datetime.now():
                raise ValidationError(_("La fecha y hora programada debe ser posterior al momento actual."))
            rec.write({"state": "scheduled"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_draft(self):
        self.write({"state": "draft"})

    def action_resend_pending(self):
        """Vuelve a notificar únicamente a los colaboradores que aún no han leído el comunicado."""
        for rec in self:
            pending_recipients = rec.recipient_ids.filtered(lambda r: not r.is_read)
            if not pending_recipients:
                raise ValidationError(_("Todos los colaboradores ya han leído este comunicado."))
            pending_employees = pending_recipients.mapped("employee_id")
            rec._notify_devices(employees=pending_employees, is_reminder=True)

    def _generate_recipients(self):
        """Genera los registros en la tabla de destinatarios según la segmentación."""
        self.ensure_one()
        emp_model = self.env["hr.employee"]

        if self.target_type == "all":
            employees = emp_model.search([("active", "=", True)])
        elif self.target_type == "department":
            if not self.department_ids:
                raise ValidationError(_("Debe seleccionar al menos un Área o Departamento."))
            employees = emp_model.search([
                ("active", "=", True),
                ("department_id", "in", self.department_ids.ids),
            ])
        elif self.target_type == "employee":
            if not self.employee_ids:
                raise ValidationError(_("Debe seleccionar al menos un colaborador."))
            employees = self.employee_ids
        else:
            employees = emp_model.browse()

        existing_emp_ids = self.recipient_ids.mapped("employee_id.id")
        to_create = []
        for emp in employees:
            if emp.id not in existing_emp_ids:
                to_create.append({
                    "news_id": self.id,
                    "employee_id": emp.id,
                    "is_read": False,
                })
        if to_create:
            self.env["mype.news.recipient"].create(to_create)

    def _notify_devices(self, employees=None, is_reminder=False):
        """
        Envía notificaciones push mediante Firebase Cloud Messaging (FCM)
        a los dispositivos vinculados (si fcm_token está disponible).
        """
        if employees is None:
            employees = self.recipient_ids.mapped("employee_id")

        if not employees:
            return

        title = ("🔔 Recordatorio: " if is_reminder else "📢 ") + (self.name or "Nueva Novedad")
        body = (self.description or "Tienes una nueva novedad o comunicado en tu buzón.")[:120]

        if "hr.employee.device" in self.env:
            self.env["hr.employee.device"].send_push_to_employees(
                employees=employees,
                title=title,
                body=body,
                data={"type": "news", "news_id": str(self.id)},
                web_link="/",
            )

    @api.model
    def _cron_publish_scheduled(self):
        """Cron ejecutado periódicamente para publicar noticias cuya hora ya llegó."""
        now = fields.Datetime.now()
        scheduled_news = self.search([
            ("state", "=", "scheduled"),
            ("scheduled_date", "<=", now),
        ])
        for news in scheduled_news:
            news.action_send_now()

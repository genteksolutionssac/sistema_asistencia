# -*- coding: utf-8 -*-
from odoo import models, fields, api


class MypeNewsRecipient(models.Model):
    _name = "mype.news.recipient"
    _description = "Destinatario y Estado de Lectura de Comunicado"
    _order = "is_read asc, id desc"

    news_id = fields.Many2one(
        "mype.news.announcement",
        string="Comunicado",
        required=True,
        ondelete="cascade",
        index=True,
    )

    employee_id = fields.Many2one(
        "hr.employee",
        string="Colaborador",
        required=True,
        ondelete="cascade",
        index=True,
    )

    employee_code = fields.Char(
        string="Código",
        related="employee_id.employee_code",
        store=True,
    )

    department_id = fields.Many2one(
        "hr.department",
        string="Área / Departamento",
        related="employee_id.department_id",
        store=True,
    )

    is_read = fields.Boolean(
        string="¿Leído?",
        default=False,
        index=True,
    )

    read_date = fields.Datetime(
        string="Fecha y Hora de Lectura",
    )

    reaction = fields.Selection(
        [
            ("like", "👍 Me gusta"),
            ("love", "❤️ Me encanta"),
            ("laugh", "😂 Me divierte"),
            ("wow", "😮 Me asombra"),
            ("sad", "😢 Me entristece"),
            ("pray", "🙏 Gracias"),
        ],
        string="Reacción",
        index=True,
    )

    reaction_date = fields.Datetime(
        string="Fecha de Reacción",
    )

    reaction_emoji = fields.Char(
        string="Emoji",
        compute="_compute_reaction_emoji",
        store=True,
    )

    @api.depends("reaction")
    def _compute_reaction_emoji(self):
        emoji_map = {
            "like": "👍",
            "love": "❤️",
            "laugh": "😂",
            "wow": "😮",
            "sad": "😢",
            "pray": "🙏",
        }
        for rec in self:
            rec.reaction_emoji = emoji_map.get(rec.reaction, "")

    _news_employee_unique = models.Constraint(
        "UNIQUE(news_id, employee_id)",
        "El colaborador ya está registrado como destinatario de este comunicado.",
    )

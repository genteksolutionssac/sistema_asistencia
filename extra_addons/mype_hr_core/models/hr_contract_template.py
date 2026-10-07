# -*- coding: utf-8 -*-
import base64
import os
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class MypeHrContractTemplate(models.Model):
    _name = "mype.hr.contract.template"
    _description = "Plantilla de Contrato Laboral (Word .docx)"
    _inherit = ["mail.thread"]
    _order = "sequence, name"

    name = fields.Char(
        string="Nombre de la plantilla",
        required=True,
        tracking=True,
        help="Nombre descriptivo de la plantilla (ej. Contrato Inicio de Nueva Actividad - MYPE).",
    )

    code = fields.Char(
        string="Código",
        tracking=True,
    )

    sequence = fields.Integer(
        string="Secuencia",
        default=10,
    )

    active = fields.Boolean(
        string="Activo",
        default=True,
    )

    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        default=lambda self: self.env.company,
        help="Compañía a la que pertenece esta plantilla (dejar vacío para uso global).",
    )

    contract_type = fields.Selection(
        [
            ("indefinite", "Indefinido"),
            ("fixed_term", "A plazo fijo / Modalidad"),
            ("part_time", "Tiempo parcial"),
            ("temporary", "Temporal"),
        ],
        string="Tipo de contrato aplicable",
        default="fixed_term",
        required=True,
        tracking=True,
    )

    legal_modality_title = fields.Char(
        string="Denominación de la modalidad",
        default="Inicio de Nueva Actividad",
        help="Título exacto de la modalidad según la ley (ej. Inicio de Nueva Actividad, Necesidad de Mercado, etc.).",
    )

    legal_base = fields.Char(
        string="Base legal",
        default="artículo 57 del Texto Único Ordenado del Decreto Legislativo N° 728",
        help="Dispositivo legal o artículo de amparo.",
    )

    default_objective_cause = fields.Text(
        string="Causa objetiva por defecto",
        help="Texto de justificación o causa objetiva que se cargará por defecto al seleccionar esta plantilla.",
    )

    file_template = fields.Binary(
        string="Archivo Plantilla Word (.docx)",
        attachment=True,
        required=True,
        help="Suba el archivo Word (.docx) que contiene las variables {{ variable }} para combinar los datos del contrato.",
    )

    file_name = fields.Char(
        string="Nombre del archivo",
        default="plantilla_contrato.docx",
    )

    description = fields.Text(
        string="Notas / Instrucciones",
        help="Instrucciones o notas adicionales sobre las variables soportadas en la plantilla.",
    )

    contract_count = fields.Integer(
        string="Contratos generados",
        compute="_compute_contract_count",
    )

    def _compute_contract_count(self):
        for template in self:
            template.contract_count = self.env["mype.hr.contract"].search_count([
                ("template_id", "=", template.id)
            ])

    def action_download_base_template(self):
        """Descarga o genera la plantilla Word base si no se ha subido una."""
        self.ensure_one()
        if not self.file_template:
            # Buscar el archivo base generado en fuentes
            base_file_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                "fuentes",
                "plantilla_contrato_trabajo_mype.docx",
            )
            if os.path.exists(base_file_path):
                with open(base_file_path, "rb") as f:
                    self.file_template = base64.b64encode(f.read())
                    self.file_name = "plantilla_contrato_trabajo_mype.docx"
            else:
                raise UserError(_("No hay un archivo de plantilla cargado en este registro."))

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content?model=mype.hr.contract.template&id={self.id}&field=file_template&filename_field=file_name&download=true",
            "target": "self",
        }

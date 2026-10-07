# -*- coding: utf-8 -*-
{
    "name": "Documentos RRHH y Firma Digital",
    "version": "19.0.1.0.0",
    "category": "Human Resources",
    "summary": "Emisión masiva de documentos laborales, plantillas oficiales y firma digital móvil",
    "description": """
Módulo de Gestión de Documentos RRHH y Firma Digital para Odoo 19:
- Plantillas oficiales de documentos laborales (Autorización de uso de imagen y voz, etc.)
- Emisión masiva a todos los colaboradores, por área o específicos
- Control en tiempo real de colaboradores que firmaron o están pendientes
- Firma digital desde el app móvil (canvas táctil y confirmación de firma guardada)
- Estampado automático de firma del gerente (desde Ajustes de Empresa) y firma del colaborador
- Sellado de tiempo UTC-5, dirección IP y hash criptográfico de auditoría
- Descarga masiva e individual de PDFs firmados
    """,
    "author": "Actitud",
    "website": "",
    "license": "LGPL-3",
    "depends": [
        "base",
        "hr",
        "mype_hr_core",
        "system_license",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "reports/paperformat.xml",
        "reports/report_authorization_image_pdf.xml",
        "data/document_template_data.xml",
        "views/document_template_views.xml",
        "views/document_assignment_views.xml",
        "views/document_batch_views.xml",
        "views/hr_employee_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}

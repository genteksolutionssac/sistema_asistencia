{
    "name": "Gestión de Personal y Horarios",
    "version": "19.0.1.0.0",
    "category": "Human Resources",
    "summary": "Gestión de colaboradores, contratos básicos, turnos y horarios de trabajo",
    "description": """
Núcleo de RR.HH. para el sistema de Asistencia y Gestión de Personal (Odoo 19).

Características:
    - Empleados (código autogenerado, datos de contacto)
    - Horarios y Turnos semanales configurables (tolerancia, entrada/salida, refrigerios)
    - Contratos laborales básicos con plantillas y asignación de turno
    """,
    "author": "Actitud",
    "website": "",
    "license": "LGPL-3",
    "depends": [
        "base",
        "hr",
        "hr_skills",
        "mail",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",

        "data/contract_template_data.xml",

        "reports/report_contract_pdf.xml",

        "views/hr_contract_views.xml",
        "views/hr_contract_template_views.xml",
        "views/hr_shift_views.xml",
        "views/hr_employee_views.xml",
        "views/res_company_views.xml",

        "views/menu_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}

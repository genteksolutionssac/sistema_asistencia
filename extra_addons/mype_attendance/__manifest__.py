{
    "name": "Asistencia y App Móvil",
    "version": "19.0.1.0.0",
    "category": "Human Resources",
    "summary": "Registros de asistencia diarios, geocercas GPS, selfies y dispositivos móviles",
    "description": """
Sistema de Asistencia y App Móvil para Odoo 19.

Características:
    - Registro de asistencia diario (mype.attendance)
    - Marcación desde la app móvil (entrada/salida con GPS y selfie)
    - Cálculo de tardanzas, salida anticipada, horas extras y horas trabajadas
    - Control y desvinculación de dispositivos móviles autorizados (hr.employee.device)
    - Configuración de sedes, coordenadas y radio de tolerancia en metros
    """,
    "author": "Actitud",
    "website": "",
    "license": "LGPL-3",
    "depends": [
        "base",
        "hr",
        "hr_homeworking",
        "mype_hr_core",
        "system_license",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",

        "data/attendance_cron.xml",
        "views/attendance_views.xml",
        "views/location_views.xml",
        "views/device_views.xml",
        "views/attendance_wizard_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}

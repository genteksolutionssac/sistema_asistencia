# -*- coding: utf-8 -*-
{
    "name": "Control de Licencias del Sistema",
    "version": "19.0.1.0.0",
    "category": "Administration",
    "summary": "Verificación y control de licencias centralizado vía Hostinger",
    "description": """
Módulo de Gestión y Bloqueo de Licencias
=========================================
- Valida la licencia con el endpoint central de Hostinger diariamente.
- Proporciona endpoint /api/license/status para la app móvil / SCADA.
- Muestra overlay y bloquea el sistema si la licencia está vencida o suspendida.
    """,
    "author": "GeneralTek Solutions",
    "website": "https://generalteksolutions.com",
    "license": "LGPL-3",
    "depends": [
        "base",
        "web",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/license_cron.xml",
        "views/license_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "system_license/static/src/css/license_overlay.css",
            "system_license/static/src/xml/license_overlay.xml",
            "system_license/static/src/js/license_overlay.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}

# -*- coding: utf-8 -*-
{
    "name": "Novedades y Comunicados de Personal",
    "version": "19.0.1.0.0",
    "category": "Human Resources",
    "summary": "Gestión de noticias, comunicados, cumpleaños y días festivos para colaboradores con integración móvil",
    "description": """
Módulo de Novedades y Comunicaciones Internas (Odoo 19).

Características:
    - Creación de comunicados, feriados, aniversarios y noticias de empresa.
    - Carga de imágenes de portada y documentos PDF adjuntos.
    - Fijación de comunicados prioritarios al inicio del buzón.
    - Segmentación por toda la empresa o por áreas/departamentos específicos.
    - Publicación inmediata o programada por fecha/hora (vía cron automático).
    - Seguimiento de lectura por colaborador (% leído vs pendiente).
    - API REST para sincronización con la app móvil y control de campanita / buzón.
    """,
    "author": "Actitud",
    "website": "",
    "license": "LGPL-3",
    "depends": [
        "base",
        "hr",
        "mype_hr_core",
        "mype_attendance",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/cron_data.xml",
        "views/news_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}

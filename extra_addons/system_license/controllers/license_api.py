# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class SystemLicenseApiController(http.Controller):

    @http.route("/api/license/status", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"], cors="*")
    def api_get_license_status(self):
        """Endpoint público que consume la app SCADA / móvil para verificar el estado de la licencia."""
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=[
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "GET, OPTIONS"),
                ("Access-Control-Allow-Headers", "Origin, X-Requested-With, Content-Type, Accept, Authorization"),
            ])

        manager = request.env["system.license.manager"].sudo()
        info = manager.get_license_public_info()

        status_code = 200 if info.get("is_active") else 402  # 402 Payment Required
        return request.make_json_response({
            "success": bool(info.get("is_active")),
            "data": info,
        }, status=status_code)

    @http.route("/api/license/verify-now", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"], cors="*")
    def api_force_verify(self):
        """Permite forzar la verificación remota inmediata con Hostinger (ej. desde el botón de la app tras pagar)."""
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=[
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "POST, OPTIONS"),
                ("Access-Control-Allow-Headers", "Origin, X-Requested-With, Content-Type, Accept, Authorization"),
            ])

        manager = request.env["system.license.manager"].sudo()
        rec = manager.get_license_record()
        rec.action_check_status()
        info = manager.get_license_public_info()

        status_code = 200 if info.get("is_active") else 402
        return request.make_json_response({
            "success": bool(info.get("is_active")),
            "data": info,
        }, status=status_code)

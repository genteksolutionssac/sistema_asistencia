# -*- coding: utf-8 -*-
import base64
import re
import unicodedata
import pytz
from odoo import http, fields
from odoo.http import request


class MypeNewsApiController(http.Controller):

    def _cors_headers(self):
        return [
            ("Access-Control-Allow-Origin", "*"),
            ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
            ("Access-Control-Allow-Headers", "Origin, X-Requested-With, Content-Type, Accept, Authorization"),
        ]

    def _authenticate_token(self):
        """Verifica la validez de la sesión del dispositivo móvil."""
        if "system.license.manager" in request.env:
            if not request.env["system.license.manager"].sudo().is_license_active():
                return None

        auth_header = request.httprequest.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        token = auth_header.split(" ")[1]
        device_rec = request.env["hr.employee.device"].sudo().search([
            ("token", "=", token),
            ("is_active", "in", ("True", "true", "1")),
        ], limit=1)
        return device_rec.employee_id if device_rec else None

    def _format_local_datetime(self, dt, employee=None):
        """Convierte un Datetime UTC a la zona horaria local (America/Lima / UTC-5)."""
        if not dt:
            return ""
        tz_name = "America/Lima"
        if employee and employee.company_id and employee.company_id.partner_id.tz:
            tz_name = employee.company_id.partner_id.tz
        elif request.env.user and request.env.user.tz:
            tz_name = request.env.user.tz

        try:
            local_tz = pytz.timezone(tz_name)
            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt)
            return dt.astimezone(local_tz).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return dt.strftime("%Y-%m-%d %H:%M")

    def _ensure_employee_recipients(self, employee):
        """
        Asegura que el colaborador tenga registros de buzón para todas
        las noticias emitidas aplicables a él.
        """
        env = request.env
        domain = [
            ("state", "=", "sent"),
            "|",
            ("target_type", "=", "all"),
            "|",
            "&", ("target_type", "=", "department"), ("department_ids", "in", [employee.department_id.id] if employee.department_id else []),
            "&", ("target_type", "=", "employee"), ("employee_ids", "in", [employee.id]),
        ]
        eligible_news = env["mype.news.announcement"].sudo().search(domain)
        existing_news_ids = env["mype.news.recipient"].sudo().search([
            ("employee_id", "=", employee.id)
        ]).mapped("news_id.id")

        to_create = []
        for news in eligible_news:
            if news.id not in existing_news_ids:
                to_create.append({
                    "news_id": news.id,
                    "employee_id": employee.id,
                    "is_read": False,
                })
        if to_create:
            env["mype.news.recipient"].sudo().create(to_create)

    @http.route("/api/news/list", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"], cors="*")
    def api_news_list(self):
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=self._cors_headers())

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        self._ensure_employee_recipients(employee)

        recipients = request.env["mype.news.recipient"].sudo().search([
            ("employee_id", "=", employee.id),
            ("news_id.state", "=", "sent"),
        ], order="id desc")

        # Ordenar: primero las fijadas (pinned), luego las más recientes
        sorted_recipients = sorted(
            recipients,
            key=lambda r: (
                1 if r.news_id.is_pinned else 0,
                r.news_id.published_date or fields.Datetime.now(),
            ),
            reverse=True,
        )

        news_list = []
        for r in sorted_recipients:
            n = r.news_id
            category_selection = dict(n._fields["category"].selection)

            # Imagen serializada en base64 para renderizado inmediato
            image_b64 = ""
            if n.file_type == "image" and n.image_cover:
                image_b64 = n.image_cover.decode("ascii") if isinstance(n.image_cover, bytes) else str(n.image_cover)

            # PDF serializado en base64 para apertura inmediata sin bloqueos de red
            pdf_b64 = ""
            if n.file_type == "pdf" and n.pdf_file:
                pdf_b64 = n.pdf_file.decode("ascii") if isinstance(n.pdf_file, bytes) else str(n.pdf_file)

            breakdown = n.get_reactions_breakdown()
            news_list.append({
                "id": n.id,
                "title": n.name,
                "category": n.category,
                "category_label": category_selection.get(n.category, n.category),
                "is_pinned": bool(n.is_pinned),
                "description": n.description or "",
                "file_type": n.file_type or "none",
                "has_image": bool(n.file_type == "image" and n.image_cover),
                "image_base64": image_b64,
                "has_pdf": bool(n.file_type == "pdf" and n.pdf_file),
                "pdf_base64": pdf_b64,
                "pdf_filename": n.pdf_filename or "comunicado.pdf",
                "published_date": self._format_local_datetime(n.published_date, employee),
                "is_read": bool(r.is_read),
                "read_date": self._format_local_datetime(r.read_date, employee),
                "my_reaction": r.reaction or None,
                "reaction_date": self._format_local_datetime(r.reaction_date, employee) if r.reaction_date else "",
                "total_reactions": breakdown["total"],
                "reactions_count": breakdown["counts"],
            })

        unread_count = sum(1 for r in sorted_recipients if not r.is_read)

        return request.make_json_response({
            "success": True,
            "news": news_list,
            "unread_count": unread_count,
        })

    @http.route("/api/news/unread_count", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"], cors="*")
    def api_news_unread_count(self):
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=self._cors_headers())

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        self._ensure_employee_recipients(employee)

        unread_count = request.env["mype.news.recipient"].sudo().search_count([
            ("employee_id", "=", employee.id),
            ("news_id.state", "=", "sent"),
            ("is_read", "=", False),
        ])

        return request.make_json_response({
            "success": True,
            "unread_count": unread_count,
        })

    @http.route("/api/news/<int:news_id>", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"], cors="*")
    def api_news_detail(self, news_id):
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=self._cors_headers())

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        news = request.env["mype.news.announcement"].sudo().browse(news_id)
        if not news.exists() or news.state != "sent":
            return request.make_json_response({"success": False, "error": "not_found"}, status=404)

        recipient = request.env["mype.news.recipient"].sudo().search([
            ("news_id", "=", news.id),
            ("employee_id", "=", employee.id),
        ], limit=1)

        category_selection = dict(news._fields["category"].selection)
        image_b64 = ""
        if news.file_type == "image" and news.image_cover:
            image_b64 = news.image_cover.decode("ascii") if isinstance(news.image_cover, bytes) else str(news.image_cover)

        pdf_b64 = ""
        if news.file_type == "pdf" and news.pdf_file:
            pdf_b64 = news.pdf_file.decode("ascii") if isinstance(news.pdf_file, bytes) else str(news.pdf_file)

        breakdown = news.get_reactions_breakdown()
        return request.make_json_response({
            "success": True,
            "news": {
                "id": news.id,
                "title": news.name,
                "category": news.category,
                "category_label": category_selection.get(news.category, news.category),
                "is_pinned": bool(news.is_pinned),
                "description": news.description or "",
                "file_type": news.file_type or "none",
                "has_image": bool(news.file_type == "image" and news.image_cover),
                "image_base64": image_b64,
                "has_pdf": bool(news.file_type == "pdf" and news.pdf_file),
                "pdf_base64": pdf_b64,
                "pdf_filename": news.pdf_filename or "comunicado.pdf",
                "published_date": self._format_local_datetime(news.published_date, employee),
                "is_read": bool(recipient and recipient.is_read),
                "read_date": self._format_local_datetime(recipient.read_date, employee) if recipient and recipient.read_date else "",
                "my_reaction": recipient.reaction if recipient and recipient.reaction else None,
                "reaction_date": self._format_local_datetime(recipient.reaction_date, employee) if recipient and recipient.reaction_date else "",
                "total_reactions": breakdown["total"],
                "reactions_count": breakdown["counts"],
            }
        })

    @http.route("/api/news/mark_all_read", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"], cors="*")
    def api_news_mark_all_read(self):
        """Marca todos los comunicados pendientes del colaborador como leídos al abrir el buzón."""
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=self._cors_headers())

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        recipients = request.env["mype.news.recipient"].sudo().search([
            ("employee_id", "=", employee.id),
            ("news_id.state", "=", "sent"),
            ("is_read", "=", False),
        ])
        count = len(recipients)
        if recipients:
            recipients.sudo().write({
                "is_read": True,
                "read_date": fields.Datetime.now(),
            })

        return request.make_json_response({
            "success": True,
            "marked_count": count,
        })

    @http.route("/api/news/<int:news_id>/read", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"], cors="*")
    def api_news_mark_read(self, news_id):
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=self._cors_headers())

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        recipient = request.env["mype.news.recipient"].sudo().search([
            ("news_id", "=", news_id),
            ("employee_id", "=", employee.id),
        ], limit=1)

        if recipient:
            recipient.sudo().write({
                "is_read": True,
                "read_date": fields.Datetime.now(),
            })

        return request.make_json_response({"success": True})

    @http.route("/api/news/<int:news_id>/file", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"], cors="*")
    def api_news_file(self, news_id):
        """Descarga o visualización directa de la imagen o documento PDF."""
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=self._cors_headers())

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        news = request.env["mype.news.announcement"].sudo().browse(news_id)
        if not news.exists():
            return request.make_json_response({"success": False, "error": "not_found"}, status=404)

        if news.file_type == "image" and news.image_cover:
            file_data = base64.b64decode(news.image_cover)
            headers = [
                ("Content-Type", "image/jpeg"),
                ("Content-Length", str(len(file_data))),
                ("Cache-Control", "no-cache"),
            ]
            return request.make_response(file_data, headers=headers)

        elif news.file_type == "pdf" and news.pdf_file:
            file_data = base64.b64decode(news.pdf_file)
            raw_filename = news.pdf_filename or "comunicado.pdf"
            # Limpiar nombre para cabecera HTTP estándar ASCII
            clean_filename = unicodedata.normalize("NFKD", raw_filename).encode("ascii", "ignore").decode("ascii")
            clean_filename = re.sub(r'[^\w\.-]', '_', clean_filename) or "comunicado.pdf"
            if not clean_filename.lower().endswith(".pdf"):
                clean_filename += ".pdf"

            headers = [
                ("Content-Type", "application/pdf"),
                ("Content-Disposition", f'inline; filename="{clean_filename}"'),
                ("Content-Length", str(len(file_data))),
                ("Cache-Control", "no-cache"),
            ]
            return request.make_response(file_data, headers=headers)

        return request.make_json_response({"success": False, "error": "no_file"}, status=404)

    @http.route("/api/news/<int:news_id>/react", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"], cors="*")
    def api_news_react(self, news_id):
        """Permite al colaborador reaccionar o desmarcar su reacción (WhatsApp style)."""
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=self._cors_headers())

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        news = request.env["mype.news.announcement"].sudo().browse(news_id)
        if not news.exists() or news.state != "sent":
            return request.make_json_response({"success": False, "error": "not_found"}, status=404)

        try:
            body = request.get_json_data() or {}
        except Exception:
            body = {}

        reaction = body.get("reaction")
        valid_reactions = ["like", "love", "laugh", "wow", "sad", "pray"]

        if reaction and reaction not in valid_reactions:
            return request.make_json_response({"success": False, "error": "invalid_reaction"}, status=400)

        recipient = request.env["mype.news.recipient"].sudo().search([
            ("news_id", "=", news.id),
            ("employee_id", "=", employee.id),
        ], limit=1)

        if not recipient:
            recipient = request.env["mype.news.recipient"].sudo().create({
                "news_id": news.id,
                "employee_id": employee.id,
                "is_read": True,
                "read_date": fields.Datetime.now(),
            })

        # Comportamiento Toggle: si presiona la misma reacción, se remueve
        if reaction and recipient.reaction == reaction:
            new_reaction = False
            new_reaction_date = False
        elif reaction in valid_reactions:
            new_reaction = reaction
            new_reaction_date = fields.Datetime.now()
        else:
            new_reaction = False
            new_reaction_date = False

        vals = {
            "reaction": new_reaction,
            "reaction_date": new_reaction_date,
        }
        # Si aún no estaba marcado como leído, marcarlo al reaccionar
        if not recipient.is_read:
            vals["is_read"] = True
            vals["read_date"] = fields.Datetime.now()

        recipient.sudo().write(vals)

        # Recalcular métricas
        news._compute_stats()
        breakdown = news.get_reactions_breakdown()

        return request.make_json_response({
            "success": True,
            "my_reaction": new_reaction or None,
            "total_reactions": breakdown["total"],
            "reactions_count": breakdown["counts"],
        })


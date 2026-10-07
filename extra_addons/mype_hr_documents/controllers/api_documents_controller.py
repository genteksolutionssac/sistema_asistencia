# -*- coding: utf-8 -*-
import base64
import json
import re
import unicodedata
from odoo import http, fields
from odoo.http import request


class MypeHrDocumentsApiController(http.Controller):

    def _cors_headers(self):
        return [
            ("Access-Control-Allow-Origin", "*"),
            ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
            ("Access-Control-Allow-Headers", "Origin, X-Requested-With, Content-Type, Accept, Authorization"),
        ]

    def _authenticate_token(self):
        """Verifica la validez de la sesión del dispositivo móvil del empleado."""
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

    @http.route("/api/documents/pending_count", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"], cors="*")
    def api_documents_pending_count(self):
        """Endpoint ultrarrápido para obtener el conteo de documentos pendientes (para badges en 5ms)."""
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=self._cors_headers())

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        count = request.env["mype.hr.document.assignment"].sudo().search_count([
            ("employee_id", "=", employee.id),
            ("state", "=", "pending"),
            ("batch_id.state", "!=", "cancel"),
        ])

        return request.make_json_response({
            "success": True,
            "pending_count": count,
        })

    @http.route("/api/documents/list", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"], cors="*")
    def api_documents_list(self):
        """Lista rápida de documentos laborales asignados sin compilar PDFs pesados en el bucle."""
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=self._cors_headers())

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        query_state = request.httprequest.args.get("state")
        domain = [
            ("employee_id", "=", employee.id),
            ("batch_id.state", "!=", "cancel"),
        ]
        if query_state and query_state in ("pending", "signed"):
            domain.append(("state", "=", query_state))

        assignments = request.env["mype.hr.document.assignment"].sudo().search(domain, order="id desc")

        pending_docs = []
        signed_docs = []

        for a in assignments:
            # Solo si ya está firmado se incluye el PDF base64 ya archivado (lectura inmediata sin compilar)
            pdf_b64 = ""
            if a.state == "signed" and a.pdf_signed:
                pdf_b64 = a.pdf_signed.decode("ascii") if isinstance(a.pdf_signed, bytes) else str(a.pdf_signed)

            doc_dict = {
                "id": a.id,
                "batch_id": a.batch_id.id,
                "batch_name": a.batch_id.name or "",
                "name": a.template_id.name or "Documento",
                "title": a.template_id.name or "Documento",
                "document_type": a.template_id.document_type or "authorization",
                "template_code": a.template_id.code or "",
                "create_date": str(a.date_issued or a.create_date or ""),
                "issue_date": str(a.date_issued or ""),
                "state": a.state,
                "date_signed": a.date_signed_local or "",
                "signed_date": a.date_signed_local or "",
                "signature_sha256": a.audit_hash or "",
                "employee_name": a.employee_id.legal_name or a.employee_id.name or "",
                "employee_dni": a.employee_id.identification_id or "",
                "requires_employee_data": False,
                "pdf_filename": a.pdf_signed_filename,
                "pdf_base64": pdf_b64,
            }

            if a.state == "pending":
                pending_docs.append(doc_dict)
            else:
                signed_docs.append(doc_dict)

        # Firma registrada del empleado (si existe)
        saved_sig_b64 = ""
        if employee.digital_signature:
            saved_sig_b64 = employee.digital_signature.decode("ascii") if isinstance(employee.digital_signature, bytes) else str(employee.digital_signature)

        all_docs = pending_docs + signed_docs

        return request.make_json_response({
            "success": True,
            "documents": all_docs,
            "pending": pending_docs,
            "signed": signed_docs,
            "count": len(all_docs),
            "pending_count": len(pending_docs),
            "has_saved_signature": bool(employee.digital_signature),
            "has_signature": bool(employee.digital_signature),
            "saved_signature_base64": saved_sig_b64,
            "signature_png_base64": saved_sig_b64,
        })

    @http.route("/api/documents/signature", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"], cors="*")
    def api_documents_signature(self):
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=self._cors_headers())

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        saved_sig_b64 = ""
        if employee.digital_signature:
            saved_sig_b64 = employee.digital_signature.decode("ascii") if isinstance(employee.digital_signature, bytes) else str(employee.digital_signature)

        return request.make_json_response({
            "success": True,
            "has_saved_signature": bool(employee.digital_signature),
            "has_signature": bool(employee.digital_signature),
            "saved_signature_base64": saved_sig_b64,
            "signature_png_base64": saved_sig_b64,
        })

    @http.route("/api/documents/<int:assignment_id>/sign", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"], cors="*")
    def api_documents_sign(self, assignment_id):
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=self._cors_headers())

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        assignment = request.env["mype.hr.document.assignment"].sudo().browse(assignment_id)
        if not assignment.exists() or assignment.employee_id.id != employee.id:
            return request.make_json_response({"success": False, "error": "not_found"}, status=404)

        if assignment.state == "signed":
            return request.make_json_response({
                "success": True,
                "message": "Documento firmado exitosamente.",
                "audit_sha256": assignment.audit_hash or "",
                "signed_date": assignment.date_signed_local,
            })

        try:
            data = json.loads(request.httprequest.data.decode("utf-8")) if request.httprequest.data else {}
        except Exception:
            data = {}

        signature_b64 = data.get("signature_base64") or data.get("signature_png_base64")
        use_saved = data.get("use_saved_signature", False)

        if use_saved and employee.digital_signature:
            signature_b64 = employee.digital_signature.decode("ascii") if isinstance(employee.digital_signature, bytes) else str(employee.digital_signature)

        if not signature_b64:
            return request.make_json_response({"success": False, "error": "missing_signature"}, status=400)

        # Obtener IP del cliente y User-Agent
        client_ip = request.httprequest.remote_addr or ""
        user_agent = request.httprequest.user_agent.string if request.httprequest.user_agent else ""

        try:
            assignment.register_signature(
                signature_b64=signature_b64,
                client_ip=client_ip,
                user_agent=user_agent,
            )
            return request.make_json_response({
                "success": True,
                "message": "Documento firmado exitosamente.",
                "audit_sha256": assignment.audit_hash or "",
                "signed_date": assignment.date_signed_local,
            })
        except Exception as e:
            return request.make_json_response({"success": False, "error": str(e)}, status=500)

    @http.route("/api/documents/<int:assignment_id>/file", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"], cors="*")
    def api_documents_file(self, assignment_id):
        """Descarga o visualización bajo demanda del PDF para un único documento."""
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=self._cors_headers())

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        assignment = request.env["mype.hr.document.assignment"].sudo().browse(assignment_id)
        if not assignment.exists() or assignment.employee_id.id != employee.id:
            return request.make_json_response({"success": False, "error": "not_found"}, status=404)

        if assignment.state == "signed" and assignment.pdf_signed:
            file_data = base64.b64decode(assignment.pdf_signed)
        else:
            file_data = assignment.render_pdf_bytes()

        raw_filename = assignment.pdf_signed_filename or "documento.pdf"
        clean_filename = unicodedata.normalize("NFKD", raw_filename).encode("ascii", "ignore").decode("ascii")
        clean_filename = re.sub(r'[^\w\.-]', '_', clean_filename) or "documento.pdf"
        if not clean_filename.lower().endswith(".pdf"):
            clean_filename += ".pdf"

        headers = [
            ("Content-Type", "application/pdf"),
            ("Content-Disposition", f'inline; filename="{clean_filename}"'),
            ("Content-Length", str(len(file_data))),
            ("Cache-Control", "no-cache"),
        ]
        return request.make_response(file_data, headers=headers)

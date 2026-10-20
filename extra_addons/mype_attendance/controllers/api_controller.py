# -*- coding: utf-8 -*-
import base64
import math
import secrets
from datetime import datetime, date
import calendar
import pytz
from werkzeug.exceptions import HTTPException
from odoo import http, fields
from odoo.http import request


class LicenseExpiredException(HTTPException):
    code = 402
    description = "License expired"

    def get_response(self, environ=None):
        return request.make_json_response({
            "success": False,
            "error": "license_expired",
            "message": "La suscripción de este sistema se encuentra vencida o suspendida por falta de pago.",
            "status_code": 402,
        }, status=402)


class MypeAttendanceMobileApi(http.Controller):

    @staticmethod
    def _clean_b64(raw):
        if not raw:
            return ""
        if "," in raw:
            return raw.split(",", 1)[1]
        return raw


    def _authenticate_token(self):
        if "system.license.manager" in request.env:
            if not request.env["system.license.manager"].sudo().is_license_active():
                raise LicenseExpiredException()

        auth_header = request.httprequest.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        token = auth_header.split(" ")[1]
        device_rec = request.env["hr.employee.device"].sudo().search([
            ("token", "=", token),
            ("is_active", "in", ("True", "true", "1")),
        ], limit=1)
        return device_rec.employee_id if device_rec else None

    @http.route("/api/auth/enroll", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"], cors="*")
    def api_enroll(self):
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=[
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                ("Access-Control-Allow-Headers", "Origin, X-Requested-With, Content-Type, Accept, Authorization"),
            ])

        if "system.license.manager" in request.env:
            if not request.env["system.license.manager"].sudo().is_license_active():
                raise LicenseExpiredException()

        try:
            data = request.get_json_data()
        except Exception:
            return request.make_json_response({"success": False, "error": "invalid_json"}, status=400)

        login = data.get("login") or data.get("username")
        password = data.get("password")
        device_id = data.get("device_id")
        phone = data.get("phone", "")
        device_model = data.get("device_model", "")

        if not login or not password or not device_id:
            return request.make_json_response({"success": False, "error": "missing_credentials_or_device"}, status=400)

        uid = False
        try:
            auth_res = request.env["res.users"].sudo().authenticate({
                "login": login,
                "password": password,
                "type": "password",
            }, {})
            if isinstance(auth_res, dict):
                uid = auth_res.get("uid")
            else:
                uid = auth_res
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Enroll authentication failed: %s", e)
            uid = False

        if not uid:
            return request.make_json_response({"success": False, "error": "invalid_login"}, status=401)

        user = request.env["res.users"].sudo().browse(uid)
        employee = request.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
        if not employee:
            return request.make_json_response({"success": False, "error": "employee_not_linked_to_user"}, status=403)

        device_model_obj = request.env["hr.employee.device"].sudo()

                # Regla 1: Un dispositivo solo puede estar vinculado a UN empleado activo.
        bound_other = device_model_obj.search([
            ("device_id", "=", device_id),
            ("is_active", "=", "True"),
            ("employee_id", "!=", employee.id),
        ], limit=1)
        if bound_other:
            return request.make_json_response({
                "success": False,
                "error": "device_bound_to_other",
                "message": "Este dispositivo ya está vinculado al colaborador %s. "
                           "Solo se permite un usuario por dispositivo. "
                           "Si cambiaste de celular, solicita a RR.HH. la desvinculación." % bound_other.employee_id.name,
                "bound_employee": bound_other.employee_id.name,
            }, status=403)

        # Regla 2 (Anti-fraude): Si el empleado ya tiene OTRO dispositivo activo vinculado, BLOQUEAR el ingreso.
        # Debe solicitar expresamente a RR.HH. la desvinculación de su equipo anterior.
        active_other_device = device_model_obj.search([
            ("employee_id", "=", employee.id),
            ("is_active", "=", "True"),
            ("device_id", "!=", device_id),
        ], limit=1)
        if active_other_device:
            device_label = active_other_device.device_model or active_other_device.phone or "otro dispositivo"
            return request.make_json_response({
                "success": False,
                "error": "employee_already_bound",
                "message": "Tu cuenta ya está vinculada al dispositivo '%s'. "
                           "Por políticas de seguridad, no puedes iniciar sesión en un nuevo equipo. "
                           "Si cambiaste de celular o PC, solicita a Recursos Humanos la desvinculación de tu equipo anterior." % device_label,
                "bound_device": device_label,
            }, status=403)

        # Si el mismo empleado ya se enroló con este dispositivo, reutilizar el token
        existing = device_model_obj.search([
            ("device_id", "=", device_id),
            ("employee_id", "=", employee.id),
        ], limit=1)
        if existing:
            if existing.is_active != "True":
                existing.write({
                    "is_active": "True",
                    "enrolled_at": fields.Datetime.now(),
                    "unbound_at": False,
                    "unbound_by": False,
                    "phone": phone or existing.phone,
                    "device_model": device_model or existing.device_model,
                    "fcm_token": data.get("fcm_token", "") or existing.fcm_token or "",
                })
            else:
                existing.write({
                    "phone": phone or existing.phone,
                    "device_model": device_model or existing.device_model,
                    "fcm_token": data.get("fcm_token", "") or existing.fcm_token or "",
                })
            return self._enroll_response(employee, existing.token)

        # Primer enrolamiento del empleado (o nuevo equipo tras desvinculación por RRHH):
        token = secrets.token_hex(32)
        device_model_obj.create({
            "employee_id": employee.id,
            "device_id": device_id,
            "token": token,
            "is_active": "True",
            "phone": phone,
            "device_model": device_model,
            "fcm_token": data.get("fcm_token", "") or "",
        })

        return self._enroll_response(employee, token)

    def _enroll_response(self, employee, token):
        return request.make_json_response({
            "success": True,
            "token": token,
            "employee": {
                "id": employee.id,
                "name": employee.name,
                "code": employee.employee_code,
                "company": employee.company_id.name,
            }
        })

    @http.route("/api/employee/profile", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"], cors="*")
    def api_profile(self):
        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        comp = employee.company_id
        use_company = employee.use_company_location
        c_lat = comp.attendance_latitude if use_company else (employee.attendance_latitude or comp.attendance_latitude or -12.0464)
        c_lng = comp.attendance_longitude if use_company else (employee.attendance_longitude or comp.attendance_longitude or -77.0428)

        user = employee.user_id
        is_dept_manager = False
        if user:
            is_hr_manager = user.has_group("mype_hr_core.group_mype_hr_manager")
            is_manager_of_dept = request.env["hr.department"].sudo().search_count([
                "|",
                ("manager_id.user_id", "=", user.id),
                ("manager_id", "=", employee.id),
            ]) > 0
            has_subordinates = request.env["hr.employee"].sudo().search_count([
                ("parent_id", "=", employee.id)
            ]) > 0
            is_dept_manager = bool(is_hr_manager or is_manager_of_dept or has_subordinates)

        today_modality = employee.get_today_modality() if hasattr(employee, "get_today_modality") else "presencial"
        effective_shift = (
            employee.effective_shift_id.name if hasattr(employee, "effective_shift_id") and employee.effective_shift_id
            else (employee.company_id.default_shift_id.name if hasattr(employee.company_id, "default_shift_id") and employee.company_id.default_shift_id else "")
        )

        is_admin = False
        if user:
            is_admin = bool(user._is_admin() or user.has_group("base.group_system") or user.has_group("base.group_erp_manager"))
        can_view_dash = bool(is_admin or is_dept_manager or (hasattr(employee, "can_view_dashboard") and employee.can_view_dashboard))

        return request.make_json_response({
            "success": True,
            "profile": {
                "id": employee.id,
                "name": employee.name,
                "code": employee.employee_code or "",
                "department": employee.department_id.name if employee.department_id else "",
                "job": employee.job_id.name if employee.job_id else "",
                "company": comp.name,
                "is_department_manager": is_dept_manager,
                "is_admin": is_admin,
                "can_view_dashboard": can_view_dash,
                "role": "manager" if is_dept_manager else "employee",
                "allowed_modality": today_modality,
                "shift_name": effective_shift,
                "geofence": {
                    "use_company_location": use_company,
                    "latitude": c_lat,
                    "longitude": c_lng,
                    "radius_meters": comp.allowed_radius_meters or 100,
                },
            }
        })

    def _local_time_str(self, dt, employee):
        """Convierte un datetime UTC (guardado en BD) a hora local de la empresa."""
        if not dt:
            return None
        tz_name = employee.company_id.partner_id.tz or "America/Lima"
        local_tz = pytz.timezone(tz_name)
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        return dt.astimezone(local_tz).strftime("%H:%M:%S")

    @http.route("/api/attendance/status", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"], cors="*")
    def api_attendance_status(self):
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=[
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                ("Access-Control-Allow-Headers", "Origin, X-Requested-With, Content-Type, Accept, Authorization"),
            ])

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        tz_name = employee.company_id.partner_id.tz or "America/Lima"
        local_tz = pytz.timezone(tz_name)
        now_local = pytz.utc.localize(datetime.now()).astimezone(local_tz)
        today = now_local.date()

        today_modality = employee.get_today_modality(today) if hasattr(employee, "get_today_modality") else "presencial"
        effective_shift = (
            employee.effective_shift_id.name if hasattr(employee, "effective_shift_id") and employee.effective_shift_id
            else (employee.company_id.default_shift_id.name if hasattr(employee.company_id, "default_shift_id") and employee.company_id.default_shift_id else "")
        )

        att = request.env["mype.attendance"].sudo().search([
            ("employee_id", "=", employee.id),
            ("date", "=", today),
        ], limit=1)

        has_entry = bool(att and att.entry_time)
        has_exit = bool(att and att.exit_time)

        next_action = "in"
        if has_entry and not has_exit:
            next_action = "out"
        elif has_entry and has_exit:
            next_action = "completed"

        return request.make_json_response({
            "success": True,
            "has_entry": has_entry,
            "has_exit": has_exit,
            "next_action": next_action,
            "allowed_modality": today_modality,
            "shift_name": effective_shift,
            "entry_time": self._local_time_str(att.entry_time, employee) if att else None,
            "exit_time": self._local_time_str(att.exit_time, employee) if att else None,
        })

    @http.route("/api/attendance/mark", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"], cors="*")
    def api_mark(self):
        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        try:
            data = request.get_json_data()
        except Exception:
            return request.make_json_response({"success": False, "error": "invalid_json"}, status=400)

        # Obtener fecha y hora en la zona local de la empresa (ej. America/Lima)
        tz_name = employee.company_id.partner_id.tz or "America/Lima"
        local_tz = pytz.timezone(tz_name)
        now_utc = datetime.now()
        now_utc_aware = pytz.utc.localize(now_utc)
        now_local = now_utc_aware.astimezone(local_tz)
        today = now_local.date()

        # Modalidad obligatoria según la programación del empleado para hoy
        allowed_modality = employee.get_today_modality(today) if hasattr(employee, "get_today_modality") else "presencial"
        modality = allowed_modality
        lat = float(data.get("latitude", 0.0))
        lng = float(data.get("longitude", 0.0))
        selfie_base64 = data.get("selfie_base64")

        # Guardar adjunto selfie si existe
        selfie_url = ""
        if selfie_base64:
            attachment = request.env["ir.attachment"].sudo().create({
                "name": f"selfie_{employee.employee_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg",
                "type": "binary",
                "datas": selfie_base64,
                "res_model": "mype.attendance",
                "res_id": 0,
            })
            selfie_url = f"/web/content/{attachment.id}?download=true"

        # Validación de geocerca si es presencial
        approval_state = "auto_approved"
        if modality == "presencial":
            comp = employee.company_id
            c_lat = employee.attendance_latitude if not employee.use_company_location else comp.attendance_latitude
            c_lng = employee.attendance_longitude if not employee.use_company_location else comp.attendance_longitude
            radius = comp.allowed_radius_meters or 100

            # Distancia Haversine en metros
            R = 6371000
            phi1, phi2 = math.radians(lat), math.radians(c_lat)
            dphi = math.radians(c_lat - lat)
            dlambda = math.radians(c_lng - lng)
            a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            distance = R * c

            if distance > radius:
                approval_state = "pending"
        else:
            approval_state = "auto_approved"

        # Crear o actualizar asistencia del día
        att_model = request.env["mype.attendance"].sudo()
        existing = att_model.search([
            ("employee_id", "=", employee.id),
            ("date", "=", today),
        ], limit=1)

        # Determinar si es entrada o salida
        mark_type = data.get("mark_type")
        if not mark_type:
            mark_type = "out" if (existing and existing.entry_time and not existing.exit_time) else "in"

        if existing:
            entry_time = now_utc if (mark_type == "in" and not existing.entry_time) else existing.entry_time
            exit_time = now_utc if mark_type == "out" else existing.exit_time
            vals = {
                "entry_time": entry_time,
                "exit_time": exit_time,
                "approval_state": approval_state,
            }
            existing.write(vals)

            shift = existing.shift_id
            if shift:
                line = request.env["mype.hr.shift.line"].sudo().search([
                    ("shift_id", "=", shift.id),
                    ("day_of_week", "=", str(today.weekday())),
                ], limit=1)
                existing.write({
                    "break_minutes": shift.break_minutes or 0.0,
                    "expected_hours": line.expected_hours if (line and line.is_working_day) else 0.0,
                })
                existing.write(att_model._compute_metrics(
                    existing.entry_time, existing.exit_time,
                    existing.scheduled_entry, existing.scheduled_exit,
                    existing.break_minutes, shift,
                ))
        else:
            shift = (
                employee.effective_shift_id
                if hasattr(employee, "effective_shift_id") and employee.effective_shift_id
                else (employee.company_id.default_shift_id if hasattr(employee.company_id, "default_shift_id") and employee.company_id.default_shift_id else False)
            )
            contract = False
            if not shift:
                contract = att_model._get_contract_on_date(employee, today)
                shift = contract.schedule_id if contract else request.env["mype.hr.shift"].sudo()
            line = request.env["mype.hr.shift.line"].sudo().search([
                ("shift_id", "=", shift.id),
                ("day_of_week", "=", str(today.weekday())),
            ], limit=1)

            sched_in = att_model._hours_to_dt(today, line.entry_time) if (line and line.is_working_day and line.entry_time is not False) else False
            sched_out = att_model._hours_to_dt(today, line.exit_time) if (line and line.is_working_day and line.exit_time is not False) else False

            record = att_model.create({
                "employee_id": employee.id,
                "employee_code": employee.employee_code,
                "company_id": employee.company_id.id,
                "date": today,
                "contract_id": contract.id if contract else False,
                "shift_id": shift.id if shift else False,
                "is_working_day": bool(line and line.is_working_day),
                "scheduled_entry": sched_in,
                "scheduled_exit": sched_out,
                "entry_time": now_utc if mark_type == "in" else False,
                "exit_time": now_utc if mark_type == "out" else False,
                "break_minutes": shift.break_minutes or 0.0,
                "expected_hours": line.expected_hours if (line and line.is_working_day) else 0.0,
                "overtime_allowed": bool(shift.allow_overtime),
                "modality": modality,
                "latitude": lat,
                "longitude": lng,
                "approval_state": approval_state,
                "origin_source": "online",
            })
            if record and record.shift_id:
                record.write(att_model._compute_metrics(
                    record.entry_time, record.exit_time,
                    record.scheduled_entry, record.scheduled_exit,
                    record.break_minutes, record.shift_id,
                ))

        return request.make_json_response({
            "success": True,
            "approval_state": approval_state,
            "server_timestamp": now_local.strftime("%Y-%m-%d %H:%M:%S"),
        })

    @http.route("/api/attendance/sync", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"], cors="*")
    def api_sync(self):
        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        try:
            data = request.get_json_data()
        except Exception:
            return request.make_json_response({"success": False, "error": "invalid_json"}, status=400)

        records = data.get("records", [])
        synced_count = 0

        att_model = request.env["mype.attendance"].sudo()
        for rec in records:
            client_time_str = rec.get("client_capture_time")
            modality = rec.get("modality", "presencial")
            lat = float(rec.get("latitude", 0.0))
            lng = float(rec.get("longitude", 0.0))
            selfie_base64 = rec.get("selfie_base64")

            try:
                client_dt = datetime.strptime(client_time_str, "%Y-%m-%d %H:%M:%S")
                today = client_dt.date()
            except Exception:
                tz_name = employee.company_id.partner_id.tz or "America/Lima"
                local_tz = pytz.timezone(tz_name)
                now_local = pytz.utc.localize(datetime.now()).astimezone(local_tz)
                today = now_local.date()

            selfie_url = ""
            if selfie_base64:
                attachment = request.env["ir.attachment"].sudo().create({
                    "name": f"sync_selfie_{employee.employee_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg",
                    "type": "binary",
                    "datas": selfie_base64,
                    "res_model": "mype.attendance",
                    "res_id": 0,
                })
                selfie_url = f"/web/content/{attachment.id}?download=true"

            existing = att_model.search([
                ("employee_id", "=", employee.id),
                ("date", "=", today),
            ], limit=1)

            now_utc = datetime.now()
            if existing:
                existing.write({
                    "exit_time": now_utc,
                    "approval_state": "pending",
                    "origin_source": "offline_sync",
                })
                shift = existing.shift_id
                if shift:
                    existing.write(att_model._compute_metrics(
                        existing.entry_time, existing.exit_time,
                        existing.scheduled_entry, existing.scheduled_exit,
                        existing.break_minutes, shift,
                    ))
            else:
                shift = (
                    employee.effective_shift_id
                    if hasattr(employee, "effective_shift_id") and employee.effective_shift_id
                    else (employee.company_id.default_shift_id if hasattr(employee.company_id, "default_shift_id") and employee.company_id.default_shift_id else False)
                )
                contract = False
                if not shift:
                    contract = att_model._get_contract_on_date(employee, today)
                    shift = contract.schedule_id if contract else request.env["mype.hr.shift"].sudo()
                line = request.env["mype.hr.shift.line"].sudo().search([
                    ("shift_id", "=", shift.id),
                    ("day_of_week", "=", str(today.weekday())),
                ], limit=1)

                sched_in = att_model._hours_to_dt(today, line.entry_time) if (line and line.is_working_day and line.entry_time is not False) else False
                sched_out = att_model._hours_to_dt(today, line.exit_time) if (line and line.is_working_day and line.exit_time is not False) else False

                record = att_model.create({
                    "employee_id": employee.id,
                    "employee_code": employee.employee_code,
                    "company_id": employee.company_id.id,
                    "date": today,
                    "contract_id": contract.id if contract else False,
                    "shift_id": shift.id if shift else False,
                    "is_working_day": bool(line and line.is_working_day),
                    "scheduled_entry": sched_in,
                    "scheduled_exit": sched_out,
                    "entry_time": now_utc,
                    "break_minutes": shift.break_minutes or 0.0,
                    "expected_hours": line.expected_hours if (line and line.is_working_day) else 0.0,
                    "overtime_allowed": bool(shift.allow_overtime),
                    "modality": modality,
                    "latitude": lat,
                    "longitude": lng,
                    "approval_state": "pending",
                    "origin_source": "offline_sync",
                })
                if record and record.shift_id:
                    record.write(att_model._compute_metrics(
                        record.entry_time, record.exit_time,
                        record.scheduled_entry, record.scheduled_exit,
                        record.break_minutes, record.shift_id,
                    ))
            synced_count += 1

        return request.make_json_response({"success": True, "synced": synced_count})

    @http.route("/api/requests/create", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"], cors="*")
    def api_create_request(self):
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=[
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                ("Access-Control-Allow-Headers", "Origin, X-Requested-With, Content-Type, Accept, Authorization"),
            ])

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        try:
            data = request.get_json_data()
        except Exception:
            return request.make_json_response({"success": False, "error": "invalid_json"}, status=400)

        req_type = data.get("type") # 'vacation' o 'medical_leave'
        pay_type = data.get("pay_type")  # 'with_pay' o 'without_pay'
        date_from = data.get("date_from")
        date_to = data.get("date_to")
        reason = data.get("reason", "")
        attachment_base64 = data.get("attachment_base64")
        attachment_name = data.get("attachment_name", "certificado.pdf")
        attachments = data.get("attachments") # [{"name": "...", "base64": "..."}]

        if not req_type or not date_from or not date_to:
            return request.make_json_response({"success": False, "error": "missing_required_fields"}, status=400)

        if req_type == "vacation":
            d_from = fields.Date.from_string(date_from)
            d_to = fields.Date.from_string(date_to)
            if d_from and d_to and d_to >= d_from:
                req_days = (d_to - d_from).days + 1
                vac_balance = getattr(employee, "vacation_balance", None)
                if vac_balance is not None and req_days > vac_balance:
                    return request.make_json_response({
                        "success": False,
                        "error": "insufficient_vacation_days",
                        "message": "Saldo insuficiente: Tienes %s días disponibles y estás solicitando %s días." % (
                            round(vac_balance, 1), req_days
                        )
                    }, status=400)

        if pay_type == "without_pay":
            permit_type = "without_pay"
        else:
            permit_type = "vacation" if req_type == "vacation" else "license"
        incident_vals = {
            "employee_id": employee.id,
            "employee_code": employee.employee_code,
            "company_id": employee.company_id.id,
            "incident_type": "permit",
            "permit_type": permit_type,
            "date_from": date_from,
            "date_to": date_to,
            "justification": reason,
            "state": "draft",
        }

        incident = request.env["mype.hr.incident"].sudo().create(incident_vals)

        files = []
        if isinstance(attachments, list):
            for att in attachments:
                if not att or not att.get("base64"):
                    continue
                files.append({
                    "name": att.get("name") or "adjunto.pdf",
                    "datas": self._clean_b64(att.get("base64")),
                })
        elif attachment_base64:
            files.append({
                "name": attachment_name,
                "datas": self._clean_b64(attachment_base64),
            })

        if files:
            created = request.env["ir.attachment"].sudo().create([
                {
                    "name": f["name"],
                    "type": "binary",
                    "datas": f["datas"],
                    "res_model": "mype.hr.incident",
                    "res_id": incident.id,
                }
                for f in files
            ])
            incident.sudo().attachment_ids = [(4, att.id) for att in created]

        return request.make_json_response({"success": True, "request_id": incident.id})

    @http.route("/api/requests/list", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"], cors="*")
    def api_list_requests(self):
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=[
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                ("Access-Control-Allow-Headers", "Origin, X-Requested-With, Content-Type, Accept, Authorization"),
            ])

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        incidents = request.env["mype.hr.incident"].sudo().search([
            ("employee_id", "=", employee.id),
        ], order="create_date desc")

        results = []
        for inc in incidents:
            req_type = "vacation"
            if inc.permit_type in ("license", "other"):
                req_type = "medical_leave"
            elif inc.permit_type == "without_pay":
                req_type = "vacation"
            results.append({
                "id": inc.id,
                "type": req_type,
                "pay_type": "without_pay" if inc.permit_type == "without_pay" else "with_pay",
                "date_from": str(inc.date_from),
                "date_to": str(inc.date_to),
                "state": inc.state, # draft, approved, rejected
                "reason": inc.justification or "",
                "notes": inc.notes or "",
            })

        return request.make_json_response({"success": True, "requests": results})

    # ---------------------------------------------------------
    # Aprobación móvil (responsable del área)
    # ---------------------------------------------------------

    @http.route("/api/requests/pending", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"], cors="*")
    def api_requests_pending(self):
        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)
        user = employee.user_id
        if not user:
            return request.make_json_response({"success": True, "requests": []})

        # Identificar si el usuario es de RR.HH.
        is_hr = user.has_group("mype_hr_core.group_mype_hr_manager")
        if not is_hr and employee.department_id:
            dept_name = (employee.department_id.name or "").lower()
            if "recursos" in dept_name or "rrhh" in dept_name or "personal" in dept_name:
                is_hr = True

        domain = [
            ("incident_type", "=", "permit"),
            ("state", "=", "draft"),
        ]

        if is_hr:
            # RR.HH. ve solicitudes asignadas a él o descansos médicos para validar
            domain.append("|")
            domain.append(("approver_id", "=", user.id))
            domain.append(("permit_type", "=", "license"))
        else:
            # Gerentes de área normal (ej. Carlos Miranda en Sistemas):
            # SOLO ven Vacaciones y permisos asignados a ellos. Descansos médicos NO les llegan.
            domain.append(("approver_id", "=", user.id))
            domain.append(("permit_type", "!=", "license"))

        incidents = request.env["mype.hr.incident"].sudo().search(domain, order="date_from asc")
        results = [self._serialize_permit(inc) for inc in incidents]
        return request.make_json_response({"success": True, "requests": results})

    @http.route("/api/requests/approve", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"], cors="*")
    def api_request_approve(self):
        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)
        user = employee.user_id
        if not user:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        try:
            data = request.get_json_data()
        except Exception:
            return request.make_json_response({"success": False, "error": "invalid_json"}, status=400)

        rid = data.get("id")
        if not rid:
            return request.make_json_response({"success": False, "error": "missing_id"}, status=400)

        incident = request.env["mype.hr.incident"].sudo().browse(rid)
        if not incident.exists():
            return request.make_json_response({
                "success": False,
                "error": "not_found",
                "message": "Solicitud no encontrada."
            }, status=404)

        # Si ya fue aprobada (ej. doble clic), responder éxito de inmediato
        if incident.state == "approved":
            return request.make_json_response({
                "success": True,
                "message": "La solicitud ya se encuentra aprobada.",
                "request": self._serialize_permit(incident.sudo())
            })

        # Validar permisos: Aprobador asignado, Gerente en la jerarquía del empleado, o RRHH
        is_hr = user.has_group("mype_hr_core.group_mype_hr_manager")
        is_assigned = (incident.approver_id.id == user.id)
        is_dept_manager = False
        dept = incident.employee_id.department_id
        while dept:
            is_leave_approver = hasattr(dept, "leave_approver_id") and dept.leave_approver_id and dept.leave_approver_id.id == user.id
            is_manager = dept.manager_id and dept.manager_id.user_id and dept.manager_id.user_id.id == user.id
            if is_leave_approver or is_manager:
                is_dept_manager = True
                break
            dept = dept.parent_id

        if not (is_assigned or is_dept_manager or is_hr):
            return request.make_json_response({
                "success": False,
                "error": "forbidden",
                "message": "No tienes permisos para aprobar esta solicitud."
            }, status=403)

        incident.sudo().action_approve()
        return request.make_json_response({
            "success": True,
            "message": "Solicitud aprobada con éxito.",
            "request": self._serialize_permit(incident.sudo())
        })

    @http.route("/api/requests/reject", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"], cors="*")
    def api_request_reject(self):
        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)
        user = employee.user_id
        if not user:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        try:
            data = request.get_json_data()
        except Exception:
            return request.make_json_response({"success": False, "error": "invalid_json"}, status=400)

        rid = data.get("id")
        reason = data.get("reason", "")
        if not rid:
            return request.make_json_response({"success": False, "error": "missing_id"}, status=400)

        incident = request.env["mype.hr.incident"].sudo().browse(rid)
        if not incident.exists():
            return request.make_json_response({
                "success": False,
                "error": "not_found",
                "message": "Solicitud no encontrada."
            }, status=404)

        if incident.state == "rejected":
            return request.make_json_response({
                "success": True,
                "message": "La solicitud ya se encuentra rechazada.",
                "request": self._serialize_permit(incident.sudo())
            })

        is_hr = user.has_group("mype_hr_core.group_mype_hr_manager")
        is_assigned = (incident.approver_id.id == user.id)
        is_dept_manager = False
        dept = incident.employee_id.department_id
        while dept:
            is_leave_approver = hasattr(dept, "leave_approver_id") and dept.leave_approver_id and dept.leave_approver_id.id == user.id
            is_manager = dept.manager_id and dept.manager_id.user_id and dept.manager_id.user_id.id == user.id
            if is_leave_approver or is_manager:
                is_dept_manager = True
                break
            dept = dept.parent_id

        if not (is_assigned or is_dept_manager or is_hr):
            return request.make_json_response({
                "success": False,
                "error": "forbidden",
                "message": "No tienes permisos para rechazar esta solicitud."
            }, status=403)

        if reason:
            incident.sudo().write({"notes": reason})
        incident.sudo().action_reject()
        return request.make_json_response({
            "success": True,
            "message": "Solicitud rechazada con éxito.",
            "request": self._serialize_permit(incident.sudo())
        })

    @http.route("/api/device/fcm", type="http", auth="none", csrf=False, methods=["POST", "OPTIONS"], cors="*")
    def api_device_fcm(self):
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=[
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                ("Access-Control-Allow-Headers", "Origin, X-Requested-With, Content-Type, Accept, Authorization"),
            ])

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)
        try:
            data = request.get_json_data()
        except Exception:
            return request.make_json_response({"success": False, "error": "invalid_json"}, status=400)
        fcm_token = data.get("fcm_token")
        if not fcm_token:
            return request.make_json_response({"success": False, "error": "missing_fcm_token"}, status=400)
        auth_header = request.httprequest.headers.get("Authorization")
        device_rec = False
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            device_rec = request.env["hr.employee.device"].sudo().search([
                ("token", "=", token),
                ("is_active", "in", ("True", "true", "1")),
            ], limit=1)
        if device_rec:
            device_rec.write({"fcm_token": fcm_token, "last_seen": fields.Datetime.now()})
        else:
            request.env["hr.employee.device"].sudo().search([
                ("employee_id", "=", employee.id),
                ("is_active", "in", ("True", "true", "1")),
            ]).write({"fcm_token": fcm_token, "last_seen": fields.Datetime.now()})
        return request.make_json_response({"success": True})


    # =========================================================================
    # DASHBOARD DE CONTROL (SUPERVISOR / ADMINISTRADOR)
    # =========================================================================

    @http.route("/api/attendance/dashboard/daily", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"], cors="*")
    def api_dashboard_daily(self):
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=[
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                ("Access-Control-Allow-Headers", "Origin, X-Requested-With, Content-Type, Accept, Authorization"),
            ])

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        comp = employee.company_id
        tz_name = comp.partner_id.tz or "America/Lima"
        local_tz = pytz.timezone(tz_name)
        now_local = pytz.utc.localize(datetime.now()).astimezone(local_tz)

        date_str = request.params.get("date")
        if date_str:
            try:
                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                target_date = now_local.date()
        else:
            target_date = now_local.date()

        dept_filter = request.params.get("department")

        # Empleados activos de la compañía
        emp_domain = [
            ("company_id", "=", comp.id),
            ("active", "=", True),
        ]
        if dept_filter and dept_filter != "TODOS":
            emp_domain.append(("department_id.name", "=", dept_filter))

        employees = request.env["hr.employee"].sudo().search(emp_domain, order="department_id, name")

        # Asistencias del día en mype.attendance
        att_records = request.env["mype.attendance"].sudo().search([
            ("company_id", "=", comp.id),
            ("date", "=", target_date),
            ("employee_id", "in", employees.ids),
        ])
        att_by_emp = {a.employee_id.id: a for a in att_records}

        # Departamentos activos
        all_comp_emps = request.env["hr.employee"].sudo().search([
            ("company_id", "=", comp.id),
            ("active", "=", True),
        ], order="department_id, name")

        dept_names = []
        for e in all_comp_emps:
            d_name = e.department_id.name if e.department_id else ""
            if d_name and d_name not in dept_names:
                dept_names.append(d_name)

        records = []
        present_count = 0
        late_count = 0
        absent_count = 0

        for emp in employees:
            att = att_by_emp.get(emp.id)

            is_leader = False
            if emp.user_id:
                is_leader = bool(
                    request.env["hr.department"].sudo().search_count([
                        "|",
                        ("manager_id.user_id", "=", emp.user_id.id),
                        ("manager_id", "=", emp.id),
                    ]) > 0 or
                    request.env["hr.employee"].sudo().search_count([("parent_id", "=", emp.id)]) > 0
                )
            else:
                is_leader = bool(
                    request.env["hr.department"].sudo().search_count([("manager_id", "=", emp.id)]) > 0 or
                    request.env["hr.employee"].sudo().search_count([("parent_id", "=", emp.id)]) > 0
                )

            entry_str = None
            exit_str = None
            late_min = 0

            if att and att.entry_time:
                entry_str = self._local_time_str(att.entry_time, emp)
                exit_str = self._local_time_str(att.exit_time, emp) if att.exit_time else None
                if att.is_late:
                    status = "late"
                    late_min = int(att.late_minutes or 0)
                    late_count += 1
                else:
                    status = "present"
                    present_count += 1
            else:
                status = "absent"
                absent_count += 1

            records.append({
                "employee": {
                    "id": emp.id,
                    "name": emp.name,
                    "code": emp.employee_code or "",
                    "job": emp.job_id.name if emp.job_id else "",
                    "department": emp.department_id.name if emp.department_id else "General",
                    "is_leader": is_leader,
                },
                "status": status,
                "entry_time": entry_str,
                "exit_time": exit_str,
                "late_minutes": late_min,
                "modality": emp.get_today_modality(target_date) if hasattr(emp, "get_today_modality") else "presencial",
            })

        return request.make_json_response({
            "success": True,
            "data": {
                "date": str(target_date),
                "total_expected": len(employees),
                "present_count": present_count,
                "late_count": late_count,
                "absent_count": absent_count,
                "departments": dept_names,
                "records": records,
            }
        })

    @http.route("/api/attendance/dashboard/history", type="http", auth="none", csrf=False, methods=["GET", "OPTIONS"], cors="*")
    def api_dashboard_history(self):
        if request.httprequest.method == "OPTIONS":
            return request.make_response("", headers=[
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                ("Access-Control-Allow-Headers", "Origin, X-Requested-With, Content-Type, Accept, Authorization"),
            ])

        employee = self._authenticate_token()
        if not employee:
            return request.make_json_response({"success": False, "error": "unauthorized"}, status=401)

        comp = employee.company_id
        tz_name = comp.partner_id.tz or "America/Lima"
        local_tz = pytz.timezone(tz_name)
        now_local = pytz.utc.localize(datetime.now()).astimezone(local_tz)

        try:
            year = int(request.params.get("year", now_local.year))
            month = int(request.params.get("month", now_local.month))
        except (ValueError, TypeError):
            year = now_local.year
            month = now_local.month

        emp_id_param = request.params.get("employee_id")
        selected_emp_id = int(emp_id_param) if emp_id_param and emp_id_param.isdigit() else None
        dept_filter = request.params.get("department")

        emp_domain = [
            ("company_id", "=", comp.id),
            ("active", "=", True),
        ]
        if dept_filter and dept_filter != "TODOS":
            emp_domain.append(("department_id.name", "=", dept_filter))

        employees = request.env["hr.employee"].sudo().search(emp_domain, order="department_id, name")
        all_comp_emps = request.env["hr.employee"].sudo().search([
            ("company_id", "=", comp.id),
            ("active", "=", True),
        ], order="department_id, name")

        dept_names = []
        for e in all_comp_emps:
            d_name = e.department_id.name if e.department_id else ""
            if d_name and d_name not in dept_names:
                dept_names.append(d_name)

        num_days = calendar.monthrange(year, month)[1]
        start_date = date(year, month, 1)
        end_date = date(year, month, num_days)

        att_domain = [
            ("company_id", "=", comp.id),
            ("date", ">=", start_date),
            ("date", "<=", end_date),
            ("employee_id", "in", employees.ids),
        ]
        monthly_atts = request.env["mype.attendance"].sudo().search(att_domain)

        att_map = {}
        for a in monthly_atts:
            att_map[(str(a.date), a.employee_id.id)] = a

        serialized_employees = []
        for e in all_comp_emps:
            is_ldr = False
            if e.user_id:
                is_ldr = bool(
                    request.env["hr.department"].sudo().search_count([
                        "|",
                        ("manager_id.user_id", "=", e.user_id.id),
                        ("manager_id", "=", e.id),
                    ]) > 0 or
                    request.env["hr.employee"].sudo().search_count([("parent_id", "=", e.id)]) > 0
                )
            else:
                is_ldr = bool(
                    request.env["hr.department"].sudo().search_count([("manager_id", "=", e.id)]) > 0 or
                    request.env["hr.employee"].sudo().search_count([("parent_id", "=", e.id)]) > 0
                )
            serialized_employees.append({
                "id": e.id,
                "name": e.name,
                "code": e.employee_code or "",
                "job": e.job_id.name if e.job_id else "",
                "department": e.department_id.name if e.department_id else "General",
                "is_leader": is_ldr,
            })

        day_records = {}
        for day in range(1, num_days + 1):
            curr_date = date(year, month, day)
            date_key = f"{year:04d}-{month:02d}-{day:02d}"

            if curr_date > now_local.date():
                continue

            staff_records = []
            present_total = 0
            late_total = 0
            absent_total = 0

            for emp in employees:
                att = att_map.get((date_key, emp.id))
                e_entry = None
                e_exit = None
                e_late_min = 0

                if att and att.entry_time:
                    e_entry = self._local_time_str(att.entry_time, emp)
                    e_exit = self._local_time_str(att.exit_time, emp) if att.exit_time else None
                    if att.is_late:
                        e_status = "late"
                        e_late_min = int(att.late_minutes or 0)
                        late_total += 1
                    else:
                        e_status = "present"
                        present_total += 1
                else:
                    e_status = "absent"
                    absent_total += 1

                staff_records.append({
                    "employee": {
                        "id": emp.id,
                        "name": emp.name,
                        "code": emp.employee_code or "",
                        "job": emp.job_id.name if emp.job_id else "",
                        "department": emp.department_id.name if emp.department_id else "General",
                        "is_leader": False,
                    },
                    "status": e_status,
                    "entry_time": e_entry,
                    "exit_time": e_exit,
                    "late_minutes": e_late_min,
                })

            total_staff = len(employees)
            rate = ((present_total + late_total) / total_staff * 100.0) if total_staff > 0 else 0.0

            ind_status = "absent"
            ind_entry = None
            ind_exit = None
            ind_late_min = 0

            if selected_emp_id:
                single_att = att_map.get((date_key, selected_emp_id))
                if single_att and single_att.entry_time:
                    ind_entry = self._local_time_str(single_att.entry_time, employee)
                    ind_exit = self._local_time_str(single_att.exit_time, employee) if single_att.exit_time else None
                    if single_att.is_late:
                        ind_status = "late"
                        ind_late_min = int(single_att.late_minutes or 0)
                    else:
                        ind_status = "present"
                else:
                    ind_status = "absent"

            day_records[date_key] = {
                "individual_status": ind_status,
                "entry_time": ind_entry,
                "exit_time": ind_exit,
                "late_minutes": ind_late_min,
                "total_staff": total_staff,
                "present_total": present_total,
                "late_total": late_total,
                "absent_total": absent_total,
                "overall_rate": round(rate, 1),
                "staff_records": staff_records,
            }

        return request.make_json_response({
            "success": True,
            "data": {
                "year": year,
                "month": month,
                "employees": serialized_employees,
                "departments": dept_names,
                "day_records": day_records,
            }
        })

    def _serialize_permit(self, inc):
        return {
            "id": inc.id,
            "employee": inc.employee_id.name,
            "employee_code": inc.employee_code,
            "type": "vacation" if inc.permit_type in ("vacation", "without_pay") else "medical_leave",
            "pay_type": "without_pay" if inc.permit_type == "without_pay" else "with_pay",
            "date_from": str(inc.date_from) if inc.date_from else "",
            "date_to": str(inc.date_to) if inc.date_to else "",
            "number_of_days": inc.number_of_days,
            "reason": inc.justification or "",
            "state": inc.state,
            "notes": inc.notes or "",
        }


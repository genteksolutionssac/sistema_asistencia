# -*- coding: utf-8 -*-
import base64
import json
import logging
import os
import time
import requests
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

# Cache de token OAuth2 en memoria de proceso
_OAUTH2_CACHE = {
    "token": None,
    "expiry": 0,
    "project_id": None,
}


class HrEmployeeDevice(models.Model):
    _name = "hr.employee.device"
    _description = "Dispositivo móvil vinculado al colaborador"
    _rec_name = "device_id"

    employee_id = fields.Many2one(
        "hr.employee",
        string="Colaborador",
        required=True,
        ondelete="cascade",
        index=True,
    )

    device_id = fields.Char(
        string="Device ID (UUID)",
        required=True,
        index=True,
    )

    token = fields.Char(
        string="Token de sesión",
        required=True,
        copy=False,
    )

    is_active = fields.Char(
        string="Activo",
        default="True",
    )

    phone = fields.Char(
        string="Celular",
        help="Número del celular donde está instalada la app.",
    )

    device_model = fields.Char(
        string="Modelo del dispositivo",
    )

    fcm_token = fields.Char(
        string="FCM Token",
        help="Token de Firebase Cloud Messaging para envío de push al dispositivo.",
    )

    last_seen = fields.Datetime(
        string="Última actividad",
    )

    enrolled_at = fields.Datetime(
        string="Fecha de enrolamiento",
        default=lambda self: fields.Datetime.now(),
    )

    unbound_at = fields.Datetime(
        string="Fecha de desvinculación",
    )

    unbound_by = fields.Many2one(
        "res.users",
        string="Desvinculado por",
    )

    def action_unbind(self):
        """Desvincula el dispositivo (invalida el token de la app)."""
        self.write({
            "is_active": "False",
            "unbound_at": fields.Datetime.now(),
            "unbound_by": self.env.user.id,
        })

    # =========================================================================
    # FIREBASE CLOUD MESSAGING (HTTP v1) ENGINE
    # =========================================================================

    @api.model
    def _get_credentials_path(self):
        """Obtiene la ruta al archivo credentials.json de Firebase."""
        custom_path = self.env["ir.config_parameter"].sudo().get_param("firebase.credentials_path")
        if custom_path and os.path.isfile(custom_path):
            return custom_path
        candidates = [
            r"C:\Users\PC\Desktop\odoo-sys\odoo-actitud\credentials.json",
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "credentials.json"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return os.path.abspath(c)
        return None

    @api.model
    def _get_firebase_access_token(self):
        """
        Genera o recupera un Access Token OAuth2 de Google para la API de Firebase v1
        usando la clave privada de credentials.json con firma RS256.
        """
        global _OAUTH2_CACHE
        now = int(time.time())

        # Si el token sigue vigente (con margen de 2 minutos), reutilizar
        if _OAUTH2_CACHE["token"] and now < (_OAUTH2_CACHE["expiry"] - 120):
            return _OAUTH2_CACHE["token"], _OAUTH2_CACHE["project_id"]

        cred_path = self._get_credentials_path()
        if not cred_path:
            _logger.warning("FCM: No se encontró el archivo credentials.json de Firebase.")
            return None, None

        try:
            with open(cred_path, "r", encoding="utf-8") as f:
                cred = json.load(f)

            client_email = cred.get("client_email")
            private_key_pem = cred.get("private_key", "").encode("utf-8")
            project_id = cred.get("project_id")

            if not client_email or not private_key_pem or not project_id:
                _logger.error("FCM: credentials.json no contiene client_email, private_key o project_id.")
                return None, None

            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding

            def b64url(b):
                return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")

            header = {"alg": "RS256", "typ": "JWT"}
            payload = {
                "iss": client_email,
                "sub": client_email,
                "aud": "https://oauth2.googleapis.com/token",
                "iat": now,
                "exp": now + 3600,
                "scope": "https://www.googleapis.com/auth/firebase.messaging",
            }

            enc_header = b64url(json.dumps(header).encode("utf-8"))
            enc_payload = b64url(json.dumps(payload).encode("utf-8"))
            to_sign = f"{enc_header}.{enc_payload}".encode("utf-8")

            priv_key = serialization.load_pem_private_key(private_key_pem, password=None)
            sig = priv_key.sign(to_sign, padding.PKCS1v15(), hashes.SHA256())
            jwt_assertion = f"{enc_header}.{enc_payload}.{b64url(sig)}"

            resp = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": jwt_assertion,
                },
                timeout=15,
            )

            if resp.status_code != 200:
                _logger.error(f"FCM: Error al obtener OAuth2 token ({resp.status_code}): {resp.text}")
                return None, None

            data = resp.json()
            access_token = data.get("access_token")
            expires_in = data.get("expires_in", 3600)

            _OAUTH2_CACHE["token"] = access_token
            _OAUTH2_CACHE["expiry"] = now + expires_in
            _OAUTH2_CACHE["project_id"] = project_id

            return access_token, project_id

        except Exception as e:
            _logger.exception(f"FCM: Excepción al generar OAuth2 token: {e}")
            return None, None

    @api.model
    def send_push_to_employees(self, employees, title, body, data=None, web_link="/"):
        """
        Envía una notificación Push vía Firebase HTTP v1 a los dispositivos activos
        vinculados a los empleados indicados.
        :param employees: recordset de hr.employee o lista de IDs
        :param title: Título visible de la notificación
        :param body: Mensaje / cuerpo
        :param data: Diccionario opcional con metadata (ej. {"type": "news", "id": "4"})
        :param web_link: Ruta destino para abrir al hacer clic (ej. "/" o "/documents")
        """
        if not employees:
            return {"sent": 0, "failed": 0}

        emp_ids = employees.ids if hasattr(employees, "ids") else list(employees)

        devices = self.search([
            ("employee_id", "in", emp_ids),
            ("is_active", "in", ("True", "true", "1")),
            ("fcm_token", "!=", False),
        ])

        if not devices:
            _logger.info(f"FCM: Ninguno de los {len(emp_ids)} empleados tiene fcm_token activo.")
            return {"sent": 0, "failed": 0}

        access_token, project_id = self._get_firebase_access_token()
        if not access_token or not project_id:
            _logger.warning("FCM: No se pudo obtener token de autenticación para enviar push.")
            return {"sent": 0, "failed": len(devices)}

        fcm_url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        str_data = {}
        if data:
            for k, v in data.items():
                str_data[str(k)] = str(v)

        sent_count = 0
        failed_count = 0
        seen_tokens = set()

        for dev in devices:
            if not dev.fcm_token or dev.fcm_token in seen_tokens:
                continue
            seen_tokens.add(dev.fcm_token)

            payload = {
                "message": {
                    "token": dev.fcm_token,
                    "notification": {
                        "title": title,
                        "body": body,
                    },
                    "data": str_data,
                    "webpush": {
                        "notification": {
                            "title": title,
                            "body": body,
                            "icon": "/icons/Icon-192.png",
                            "badge": "/icons/Icon-192.png",
                        },
                        "fcm_options": {
                            "link": web_link or "/",
                        },
                    },
                }
            }

            try:
                resp = requests.post(fcm_url, headers=headers, json=payload, timeout=10)
                if resp.status_code == 200:
                    sent_count += 1
                else:
                    err_body = resp.text
                    _logger.warning(f"FCM: Falló envío a dispositivo {dev.id} ({resp.status_code}): {err_body}")
                    failed_count += 1
                    if "UNREGISTERED" in err_body or "NOT_FOUND" in err_body:
                        dev.write({"fcm_token": False})
            except Exception as e:
                _logger.error(f"FCM: Error de red al enviar a {dev.id}: {e}")
                failed_count += 1

        _logger.info(f"FCM: Envió push '{title}'. Exitosos: {sent_count}, Fallidos: {failed_count}")
        return {"sent": sent_count, "failed": failed_count}

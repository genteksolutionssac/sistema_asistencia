# -*- coding: utf-8 -*-
import logging
import requests
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# =========================================================================
# 🔑 CONFIGURACIÓN DE LICENCIA HOSTINGER
# Coloca aquí tu token de Hostinger (Bearer Token) cuando lo tengas listo:
# Ejemplo: "gtk_a8f93b019c4d28e7710a9"
# =========================================================================
HOSTINGER_BEARER_TOKEN = "JFq2gv0PjocFLDKJRCJPPHijVr2qyV9eCwCdYpHI2hIf9DEGIyfWfQWRreBVl23X"
HOSTINGER_ENDPOINT_URL = "https://generalteksolutions.com/api/check-status.php"


class SystemLicenseManager(models.Model):
    _name = "system.license.manager"
    _description = "Gestión Centralizada de Licencia del Sistema"

    name = fields.Char(string="Descripción", default="Licencia Principal del Sistema", required=True)
    token = fields.Char(
        string="Token de Consulta (Bearer)",
        default=lambda self: HOSTINGER_BEARER_TOKEN,
        help="Token secreto para consultar el estado en Hostinger (Authorization: Bearer <token>)"
    )
    endpoint_url = fields.Char(
        string="URL del Endpoint",
        default=HOSTINGER_ENDPOINT_URL,
        required=True,
        help="URL completa del script check-status.php en Hostinger"
    )
    is_active = fields.Boolean(
        string="Licencia Activa",
        default=True,
        help="Indica si el sistema tiene permiso de uso activo"
    )
    status = fields.Selection([
        ("activo", "Activo / Pagado"),
        ("suspendido", "Suspendido"),
        ("vencido", "Vencido"),
        ("sin_verificar", "Sin Verificar"),
        ("error_conexion", "Error de Conexión"),
    ], string="Estado", default="sin_verificar")

    client_name = fields.Char(string="Nombre del Cliente Registrado", readonly=True)
    expiration_date = fields.Date(string="Fecha de Vencimiento", readonly=True)
    last_checked = fields.Datetime(string="Última Verificación", readonly=True)
    last_message = fields.Text(string="Mensaje del Servidor / Diagnóstico", readonly=True)

    @api.model
    def get_license_record(self):
        """Retorna o crea el registro único de configuración de licencia."""
        record = self.sudo().search([], limit=1)
        if not record:
            record = self.sudo().create({
                "name": "Licencia Principal del Sistema",
                "token": HOSTINGER_BEARER_TOKEN,
                "endpoint_url": HOSTINGER_ENDPOINT_URL,
                "is_active": True,
                "status": "sin_verificar",
            })
        return record

    @api.model
    def is_license_active(self):
        """Verifica rápidamente si la licencia actual está activa."""
        rec = self.get_license_record()
        # Si tiene token por defecto y nunca se ha verificado, permitir operar mientras se configura
        if rec.token == "PEGA_AQUI_TU_TOKEN_GTK" and rec.status == "sin_verificar":
            return True
        return bool(rec.is_active)

    def action_check_status(self):
        """Consulta el endpoint de Hostinger y actualiza el estado del sistema."""
        self.ensure_one()
        token = (self.token or "").strip()
        url = (self.endpoint_url or "").strip()

        if not token or token == "PEGA_AQUI_TU_TOKEN_GTK":
            self.write({
                "status": "sin_verificar",
                "last_message": "Token de Hostinger no configurado. Configure un token válido.",
                "last_checked": fields.Datetime.now(),
            })
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Token pendiente"),
                    "message": _("Por favor ingrese un token de consulta válido de Hostinger."),
                    "type": "warning",
                    "sticky": False,
                }
            }

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "Odoo-System-License-Client/1.0",
        }

        today = fields.Date.today()

        try:
            _logger.info("system_license: Consultando endpoint %s", url)
            response = requests.get(url, headers=headers, timeout=10)
            status_code = response.status_code
            _logger.info("system_license: Respuesta recibida: HTTP %s", status_code)

            if status_code == 200:
                try:
                    data = response.json()
                except Exception:
                    data = {}

                valido = data.get("valido", False)
                estado_raw = str(data.get("estado", "")).lower()
                fecha_venc_raw = data.get("fecha_vencimiento")
                cliente_nombre = data.get("cliente_nombre") or ""

                fecha_venc = None
                if fecha_venc_raw:
                    try:
                        fecha_venc = fields.Date.from_string(fecha_venc_raw)
                    except Exception:
                        fecha_venc = None

                # Determinar si está activo y al día
                is_valid = bool(valido) and (estado_raw == "activo" or not estado_raw)
                if fecha_venc and fecha_venc < today:
                    is_valid = False
                    computed_status = "vencido"
                    msg = f"Licencia vencida el {fecha_venc}. Regularice el pago para reactivar."
                elif is_valid:
                    computed_status = "activo"
                    msg = f"Licencia activa y al día. Vence: {fecha_venc or 'Sin fecha límite'}."
                else:
                    computed_status = "suspendido"
                    msg = f"Licencia suspendida por el administrador (Hostinger)."

                self.write({
                    "is_active": is_valid,
                    "status": computed_status,
                    "client_name": cliente_nombre,
                    "expiration_date": fecha_venc,
                    "last_checked": fields.Datetime.now(),
                    "last_message": msg,
                })

            elif status_code in (401, 403):
                # Token inválido o revocado
                self.write({
                    "is_active": False,
                    "status": "suspendido",
                    "last_checked": fields.Datetime.now(),
                    "last_message": f"Servidor denegó acceso (HTTP {status_code}): Token no válido o revocado.",
                })
            else:
                self.write({
                    "is_active": False,
                    "status": "suspendido",
                    "last_checked": fields.Datetime.now(),
                    "last_message": f"Error inesperado del servidor Hostinger: HTTP {status_code}",
                })

        except requests.exceptions.RequestException as e:
            _logger.warning("system_license: Error de conexión con Hostinger: %s", e)
            # Tolerancia de red: si se verificó con éxito en las últimas 48 horas, mantener estado previo
            hours_since_last_check = 999
            if self.last_checked:
                delta = datetime.now() - fields.Datetime.from_string(self.last_checked)
                hours_since_last_check = delta.total_seconds() / 3600

            if hours_since_last_check <= 48 and self.expiration_date and self.expiration_date >= today:
                _logger.info("system_license: Operando bajo período de gracia de red (último chequeo hace %.1fh)", hours_since_last_check)
                self.write({
                    "last_message": f"Fallo temporal de conexión con Hostinger. Operando en gracia ({e}).",
                })
            else:
                self.write({
                    "is_active": False,
                    "status": "error_conexion",
                    "last_message": f"No se pudo contactar el servidor de licencias Hostinger: {e}",
                })

        # Notificación en la interfaz de Odoo
        msg_type = "success" if self.is_active else "danger"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Verificación de Licencia"),
                "message": self.last_message,
                "type": msg_type,
                "sticky": not self.is_active,
            }
        }

    @api.model
    def cron_daily_license_check(self):
        """Método invocado diariamente por ir.cron para consultar Hostinger."""
        rec = self.get_license_record()
        _logger.info("system_license: Ejecutando verificación automática diaria de licencia...")
        rec.action_check_status()
        return True

    @api.model
    def get_license_public_info(self):
        """Retorna información segura sobre el estado de la licencia para el frontend y la app móvil."""
        rec = self.get_license_record()
        return {
            "is_active": bool(rec.is_active),
            "status": rec.status or "sin_verificar",
            "client_name": rec.client_name or "",
            "expiration_date": str(rec.expiration_date) if rec.expiration_date else None,
            "last_checked": str(rec.last_checked) if rec.last_checked else None,
            "message": rec.last_message or ("Sistema activo" if rec.is_active else "Licencia inactiva o suspendida."),
        }

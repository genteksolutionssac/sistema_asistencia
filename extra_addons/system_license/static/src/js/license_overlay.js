/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class LicenseLockoutOverlay extends Component {
    static template = "system_license.LicenseLockoutOverlay";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            isBlocked: false,
            loading: false,
            clientName: "",
            expirationDate: "",
            message: "",
        });

        onWillStart(async () => {
            await this.checkLicense();
        });
    }

    async checkLicense() {
        try {
            const info = await this.orm.call("system.license.manager", "get_license_public_info", []);
            if (info) {
                this.state.isBlocked = !info.is_active;
                this.state.clientName = info.client_name;
                this.state.expirationDate = info.expiration_date;
                this.state.message = info.message;
            }
        } catch (e) {
            console.warn("system_license: Error al comprobar licencia:", e);
        }
    }

    async onRetryClick() {
        this.state.loading = true;
        try {
            await this.orm.call("system.license.manager", "cron_daily_license_check", []);
            await this.checkLicense();
            if (!this.state.isBlocked) {
                this.notification.add("Licencia verificada exitosamente. El sistema está activo.", {
                    type: "success",
                });
            } else {
                this.notification.add("La licencia continúa inactiva o no pagada en Hostinger.", {
                    type: "danger",
                });
            }
        } catch (e) {
            this.notification.add("Error al conectar con el servidor de licencias: " + e, {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
        }
    }
}

registry.category("main_components").add("LicenseLockoutOverlay", {
    Component: LicenseLockoutOverlay,
});

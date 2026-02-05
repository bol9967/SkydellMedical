/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";

/**
 * Widget to display a QR code image from a URL field
 */
class ReferralQrCodeWidget extends Component {
    static template = "ox_doctor_referral_program.ReferralQrCodeWidget";
    static props = {
        "*": true,
    };

    get qrCodeUrl() {
        return this.props.record.data[this.props.name] || "";
    }

    get hasQrCode() {
        return Boolean(this.qrCodeUrl);
    }
}

// Register the widget
registry.category("fields").add("referral_qr_code", {
    component: ReferralQrCodeWidget,
    supportedTypes: ["char"],
});

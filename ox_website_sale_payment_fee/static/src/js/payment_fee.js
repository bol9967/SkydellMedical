/** @odoo-module **/

import { rpc } from '@web/core/network/rpc';
import publicWidget from '@web/legacy/js/public/public_widget';

publicWidget.registry.PaymentFee = publicWidget.Widget.extend({
    // Restrict to website checkout payment block only.
    // Backend / portal payment forms render only #o_payment_form without #payment_method,
    // so this prevents our logic (and reloads) from running there.
    selector: '#payment_method',
    events: {
        'change input[name="o_payment_radio"]': '_onPaymentOptionChange',
    },

    /**
     * @override
     */
    async start() {
        await this._super(...arguments);
        this._updatingFee = false;
        
        // Note: We don't call _updatePaymentFee() on page load because
        // the controller (_get_shop_payment_values) already handles adding
        // the fee when the page loads. We only update when user changes selection.
    },

    /**
     * Handle payment option change (token or payment method)
     */
    _onPaymentOptionChange(ev) {
        const input = ev.currentTarget;
        // Only process if the input is actually checked
        if (!input.checked) {
            return;
        }
        
        const providerId = input.dataset.providerId;
        if (providerId) {
            this._updatePaymentFee(providerId);
        }
    },

    /**
     * Update payment fee via RPC
     * Only called when user explicitly changes payment option
     */
    async _updatePaymentFee(providerId) {
        // Prevent multiple simultaneous calls
        if (this._updatingFee) {
            return;
        }

        this._updatingFee = true;
        
        try {
            const result = await rpc('/shop/payment/update_fee', {
                provider_id: providerId ? parseInt(providerId) : null,
            });
            
            if (result.error) {
                console.error('Error updating payment fee:', result.error);
                this._updatingFee = false;
                return;
            }

            // Fee is updated server-side; avoid reloading so the user
            // keeps their selection and can proceed smoothly.
            this._updatingFee = false;
        } catch (error) {
            console.error('Error updating payment fee:', error);
            this._updatingFee = false;
        }
    },
});

export default publicWidget.registry.PaymentFee;


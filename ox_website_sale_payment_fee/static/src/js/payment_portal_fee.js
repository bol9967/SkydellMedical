/** @odoo-module **/

import { rpc } from '@web/core/network/rpc';
import publicWidget from '@web/legacy/js/public/public_widget';

publicWidget.registry.PaymentPortalFee = publicWidget.Widget.extend({
    selector: '#o_payment_form',
    events: {
        'change input[name="o_payment_radio"]': '_onPaymentOptionChange',
    },

    /**
     * @override
     */
    async start() {
        await this._super(...arguments);
        this._updatingFee = false;
        
        // Get invoice_id or sale_order_id from form data attributes
        const form = this.el.querySelector('form#o_payment_form');
        if (form) {
            this.invoiceId = form.dataset.invoiceId || null;
            this.saleOrderId = form.dataset.saleOrderId || null;
        }
        
        // Fallback: Get from URL params
        if (!this.invoiceId && !this.saleOrderId) {
            const urlParams = new URLSearchParams(window.location.search);
            this.invoiceId = urlParams.get('move_id') || urlParams.get('invoice_id') || null;
            this.saleOrderId = urlParams.get('sale_order_id') || null;
        }
    },

    /**
     * Handle payment option change
     */
    _onPaymentOptionChange(ev) {
        const input = ev.currentTarget;
        // Only process if the input is actually checked
        if (!input.checked) {
            return;
        }
        
        const providerId = input.dataset.providerId || input.closest('[data-provider-id]')?.dataset.providerId;
        if (providerId) {
            this._updatePaymentFee(providerId);
        }
    },

    /**
     * Update payment fee amount when provider is selected
     * Adds the fee product to sale order/invoice in the background
     * Customer will see the updated amount after payment is completed
     */
    async _updatePaymentFee(providerId) {
        // Prevent multiple simultaneous calls
        if (this._updatingFee) {
            return;
        }

        this._updatingFee = true;
        
        try {
            // Silently add the fee product to sale order/invoice
            // No page reload, no UI update - customer will see it after payment
            await rpc('/payment/update_fee_amount', {
                provider_id: providerId ? parseInt(providerId) : null,
                invoice_id: this.invoiceId ? parseInt(this.invoiceId) : null,
                sale_order_id: this.saleOrderId ? parseInt(this.saleOrderId) : null,
            });
            
            this._updatingFee = false;
        } catch (error) {
            console.error('Error updating payment fee:', error);
            this._updatingFee = false;
        }
    },
});

export default publicWidget.registry.PaymentPortalFee;


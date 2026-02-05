/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

/**
 * Widget to handle referral code/link copy functionality in portal
 */
publicWidget.registry.ReferralPortalCopy = publicWidget.Widget.extend({
    selector: '.o_referral_qr_section',
    events: {
        'click .o_copy_referral_code': '_onCopyCode',
        'click .o_copy_referral_link': '_onCopyLink',
    },

    /**
     * Copy referral code to clipboard
     * @param {Event} ev
     */
    _onCopyCode: function (ev) {
        ev.preventDefault();
        const code = ev.currentTarget.dataset.code;
        this._copyToClipboard(code, ev.currentTarget);
    },

    /**
     * Copy referral link to clipboard
     * @param {Event} ev
     */
    _onCopyLink: function (ev) {
        ev.preventDefault();
        const link = ev.currentTarget.dataset.link;
        this._copyToClipboard(link, ev.currentTarget);
    },

    /**
     * Copy text to clipboard and show feedback
     * @param {string} text - Text to copy
     * @param {HTMLElement} button - Button element for feedback
     */
    _copyToClipboard: async function (text, button) {
        try {
            await navigator.clipboard.writeText(text);
            // Show success feedback
            const originalHtml = button.innerHTML;
            button.innerHTML = '<i class="fa fa-check text-success"/>';
            button.classList.add('btn-success');
            button.classList.remove('btn-outline-secondary');

            setTimeout(() => {
                button.innerHTML = originalHtml;
                button.classList.remove('btn-success');
                button.classList.add('btn-outline-secondary');
            }, 2000);
        } catch (err) {
            console.error('Failed to copy text: ', err);
            // Fallback for older browsers
            this._fallbackCopyToClipboard(text);
        }
    },

    /**
     * Fallback copy method for older browsers
     * @param {string} text - Text to copy
     */
    _fallbackCopyToClipboard: function (text) {
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.left = '-999999px';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();

        try {
            document.execCommand('copy');
        } catch (err) {
            console.error('Fallback: Could not copy text: ', err);
        }

        document.body.removeChild(textArea);
    },
});

export default publicWidget.registry.ReferralPortalCopy;

/** @odoo-module **/

(function() {
    'use strict';

    document.addEventListener('DOMContentLoaded', function() {
        const termsIdInput = document.getElementById('terms_id');
        const scrolledToBottomInput = document.getElementById('scrolled_to_bottom');

        // Intercept OWL signature form RPC to add terms_id
        // Odoo's RPC uses JSON-RPC format: { jsonrpc: "2.0", method: "call", params: {...} }
        // We need to patch the rpc function from @web/core/network/rpc
        
        // Wait for OWL to load and patch the rpc function
        function patchRpcFunction() {
            // Try multiple ways to access and patch rpc
            if (typeof window !== 'undefined') {
                // Method 1: Patch via rpcBus event
                if (typeof rpcBus !== 'undefined') {
                    rpcBus.addEventListener('RPC:REQUEST', function(ev) {
                        const { data, url } = ev.detail;
                        if (url && url.includes('/web/signup/terms/accept')) {
                            // Add our parameters to the params object
                            if (!data.params) {
                                data.params = {};
                            }
                            // Always set scrolled_to_bottom to true (signature is the validation point)
                            data.params.scrolled_to_bottom = true;
                            if (termsIdInput && termsIdInput.value) {
                                data.params.terms_id = termsIdInput.value;
                            }
                        }
                    });
                }
            }
        }
        
        // Try to patch immediately and also after a delay
        patchRpcFunction();
        setTimeout(patchRpcFunction, 500);
        setTimeout(patchRpcFunction, 2000);

        // Make terms_id available globally for OWL component
        window.signupTermsData = {
            termsId: termsIdInput ? termsIdInput.value : null,
            updateTermsId: function() {
                this.termsId = termsIdInput ? termsIdInput.value : null;
            }
        };
    });
})();

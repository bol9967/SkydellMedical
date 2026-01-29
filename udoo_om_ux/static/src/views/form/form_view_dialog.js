/** @odoo-module **/

import { patch } from '@web/core/utils/patch';
import { useService } from '@web/core/utils/hooks';
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";

// ========== ✅ ADDED: Track if Chatter is available ==========
// Track if Chatter is available
let chatterAvailable = false;

// ========== ✅ CHANGED: Replaced synchronous import with lazy loading ==========
// ❌ REMOVED: import { Chatter } from '@mail/chatter/web_portal/chatter';
// Conditionally import and register Chatter only if available (backend context)
// Use lazy loading to avoid errors in frontend context
import('@mail/chatter/web_portal/chatter').then((module) => {
    if (module.Chatter) {
        chatterAvailable = true;
        FormViewDialog.components = { ...FormViewDialog.components, Chatter: module.Chatter };
    }
}).catch(() => {
    // Chatter module not available (e.g., in frontend context) - this is expected
    // Do not register Chatter component
    chatterAvailable = false;
});

patch(FormViewDialog.prototype, {
    setup() {
        this.dropinCls = '';
        super.setup();
        this.ui = useService('ui');
        // ========== ✅ ADDED: Initialize chatterAvailable flag ==========
        // Initialize chatterAvailable flag
        this.chatterAvailable = chatterAvailable;
    },
    // ========== ✅ ADDED: New getter method to check if Chatter component exists ==========
    get hasChatterComponent() {
        // Check if Chatter component is available in FormViewDialog components
        // Also check the flag in case async import hasn't completed yet
        return (FormViewDialog.components && FormViewDialog.components.Chatter !== undefined) || this.chatterAvailable;
    }
});

// ========== ❌ REMOVED: Direct component registration (moved inside .then() block) ==========
// ❌ REMOVED: FormViewDialog.components = { ...FormViewDialog.components, Chatter }

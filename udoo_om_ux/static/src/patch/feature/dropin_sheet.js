import { patch } from '@web/core/utils/patch';
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";


patch(FormViewDialog.prototype, {
    setup() {
        super.setup();
        this.dropinCls = 'u_dsheet';
    }
});

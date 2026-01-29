import { patch } from '@web/core/utils/patch';
import { OmuxConf } from '@udoo_om_ux/conf/view';

patch(OmuxConf.prototype, {
    openAppGroupSett() {
        this.env.dialogData.close();
        this.action.doAction('udoo_lavend_ux.action_app_group');
    },

    openCoSchemeSett() {
        this.action.doAction('omux_color_scheme.open_module_config');
    },
});
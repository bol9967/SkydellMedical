import { patch } from '@web/core/utils/patch';
import { OmuxNavBar } from '@udoo_om_ux/webclient/navbar/navbar';

patch(OmuxNavBar.prototype, {
    preSubnavTiming(ev, appsub) {
        if (this.mipop.isOpen) super.preSubnavTiming(ev, appsub);
    }
});
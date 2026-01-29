import { patch } from '@web/core/utils/patch';
import { OmuxNavBar } from '@udoo_om_ux/webclient/navbar/navbar';
import { onWillStart } from '@odoo/owl';

patch(OmuxNavBar.prototype, {
    setup() {
        super.setup();

        onWillStart(async () => {
            const companyId = this.ui.cpyId();
            const sidenavBg = `linear-gradient(to bottom, color-mix(in srgb, var(--primary) 2%,#14141466), rgba(7,7,7,0.5)), url('/web/image/res.company/${companyId}/${this.ui.color_scheme === 'dark' ? 'snbg_lui' : 'snbg_dui'}')`;

            document.documentElement.style.setProperty('--uw-sidenav-bg', sidenavBg);
        });
    },
});
import { patch } from '@web/core/utils/patch';
import { OmuxNavBar } from '@udoo_om_ux/webclient/navbar/navbar';
import { onWillStart } from '@odoo/owl';

patch(OmuxNavBar.prototype, {
    setup() {
        super.setup();

        this.appGroupDict = {};

        onWillStart(async () => {
            const groupDefs = await this.orm.call(
                'ir.ui.menu.group',
                'omux_data',
            );
            this.appGroups = groupDefs.map(group => ({
                ...group,
                items: this.menuApps.filter(app => group.items.includes(app.id))
            }));

            // Build grouped lookup dict
            this.appGroups.forEach(group => {
                group.items.forEach(app => {
                    this.appGroupDict[app.id] = true;
                });
            });
            if (!Object.keys(this.appGroupDict).length) {
                this._noAppGroup = true;
            }
        });
    },

    onIslandContext(ev) {
        const el = ev.target.closest('a');
        this.uState.currentMenuXmlid = el.dataset.menuXmlid;
        this.mapop.open(el, {
            widget: this,
            grouped: this.appGroupDict[el.dataset.appid],
        });
    },

    _getSuiView() {
        if (!this._noAppGroup) {
            return 'app';
        }
        return super._getSuiView();
    }
});
import { patch } from '@web/core/utils/patch';

import { ControlPanel } from '@web/search/control_panel/control_panel';


patch(ControlPanel.prototype, {
    setup() {
        this.useGlobalFilterBar = true;
        super.setup();
    },
});
import { patch } from '@web/core/utils/patch';
import { useBus } from '@web/core/utils/hooks';

import { ListRenderer } from '@web/views/list/list_renderer';

patch(ListRenderer.prototype, {
    setup() {
        super.setup();

        useBus(this.env.bus, 'LYT:RESET', () => {
            this.columnWidths.resetColumnWidths?.();
            window.dispatchEvent(new Event('resize'));
        });
    }
});

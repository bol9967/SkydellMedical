import { _t } from '@web/core/l10n/translation';
import { patch } from '@web/core/utils/patch';

import { FormController } from '@web/views/form/form_controller';


patch(FormController.prototype, {

    async onPagerUpdate({ offset, resIds }) {
        await super.onPagerUpdate({ offset, resIds });
        this.env.bus.trigger('LSF:RESET');
    }
});
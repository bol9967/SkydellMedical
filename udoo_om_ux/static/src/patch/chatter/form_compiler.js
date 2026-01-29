/* @odoo-module */

import { patch } from '@web/core/utils/patch';
import { SIZES } from '@web/core/ui/ui_service';
import { createElement, setAttributes } from '@web/core/utils/xml';
import { FormCompiler } from '@web/views/form/form_compiler';


patch(FormCompiler.prototype, {

    compile(node, params) {
        const res = super.compile(node, params);

        const chatterContainerHookXml = res.querySelector('.o_form_renderer>.o-mail-Form-chatter');
        const formSheetBgXml = res.querySelector('.o_form_sheet_bg');

        if (chatterContainerHookXml && formSheetBgXml) {

            setAttributes(formSheetBgXml, {
                't-att-class': `{'xl_sheet': __comp__.uiService.size == ${SIZES.XL}}`,
            });

            const chatterContainerXml = chatterContainerHookXml.querySelector(
                "t[t-component='__comp__.mailComponents.Chatter']"
            );

            if (chatterContainerXml) {
                const atpv = res.querySelector('.o_attachment_preview');
                const form = res.querySelector('.o_form_renderer');
                const attf = form.getAttribute('t-attf-class');
                form.setAttribute('t-attf-class', attf.replace('? "flex-column"', ` and (!__comp__.uCommboSize or ${atpv ? 'false' : 'true'}) ? "flex-column"`));
                res.prepend(this.monacoSashContainer);
            }
        }

        if (res.querySelector(`Widget[name="'todo_chatter_panel'"]`)) {
            res.prepend(this.monacoSashContainer);
        }

        return res;
    },

    get monacoSashContainer() {
        const sashContainer = createElement('div', {
            'class': 'sash-container',
            't-if': `!__comp__.yy.noaside and __comp__.uiService.size > 4 and !(__comp__.ue and __comp__.ue.sett_uisize > 4)`,
        });
        const monacoSash = createElement('div', {
            'class': 'monaco-sash vertical',
            't-on-mousedown.prevent.stop.capture': '(ev) => __comp__.onSassAsideStart(ev)',
            't-att-class': '{"sizing": __comp__.yy.sashMarkPoint}',
        });
        sashContainer.append(monacoSash);
        return sashContainer;
    }
});
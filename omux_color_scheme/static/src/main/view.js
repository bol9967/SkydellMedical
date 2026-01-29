import { LazyComponent } from '@web/core/assets';
import { registry } from '@web/core/registry';
import { Component, xml } from '@odoo/owl';

export class ModuleConfigLoader extends Component {
    static template = xml`<LazyComponent bundle="'omux_color_scheme.conf'" Component="'ColorPaletteConfig'"/>`;
    static components = { LazyComponent };
    static props = { '*': true };
}

registry.category('actions').add('omux_color_scheme_config', ModuleConfigLoader);
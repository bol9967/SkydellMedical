import { _t } from '@web/core/l10n/translation';
import { condition } from '@web/core/tree_editor/condition_tree';
import { getDefaultValue } from '@web/core/tree_editor/tree_editor_value_editors';
import { Component, useState } from '@odoo/owl';
import { DomainSelector } from '@web/core/domain_selector/domain_selector';

import { getDomainDisplayedOperators } from '../editor/domain_selector_operator_editor';


const SPECIAL_FIELDS = ['country_id', 'user_id', 'partner_id', 'stage_id', 'id'];


export function getDefaultPath(fieldDefs, forceFieldPath) {
    const name = fieldDefs[forceFieldPath];
    if (name) {
        return forceFieldPath;
    }
    for (const name of SPECIAL_FIELDS) {
        const fieldDef = fieldDefs[name];
        if (fieldDef) {
            return fieldDef.name;
        }
    }
    throw new Error(`No field found`);
}


export class DataFilter extends DomainSelector {
    static template = 'wub.DataFilter';
    static props = {
        ...DomainSelector.props, forceFieldPath: { type: String, optional: true },
    }

    getDefaultCondition(fieldDefs) {
        const defaultPath = getDefaultPath(fieldDefs, this.props.forceFieldPath);
        const fieldDef = fieldDefs[defaultPath];
        const operator = getDomainDisplayedOperators(fieldDef)[0];
        const value = getDefaultValue(fieldDef, operator);
        return condition(fieldDef.name, operator, value);
    }
}

export class FieldFilterPopup extends Component {
    static components = { DataFilter }
    static template = 'wub.FieldFilterPopup'
    static props = { '*': true };

    setup() {
        super.setup();
        this.orgDomain = this.props.domain;
        this.state = useState({ domain: this.props.domain });
    }

    apply() {
        this.props.applyDomain(this.props.forceFieldPath);
        this.props.close();
    }

    reset() {
        this.state.domain = this.orgDomain;
        this.props.update(this.orgDomain, this.props.forceFieldPath);
    }

    clear() {
        this.props.widget._clearColumnFilter(this.props.forceFieldPath);
        this.props.close();
    }

    get domainSelectorProps() {
        return {
            className: this.props.className,
            resModel: this.props.resModel,
            readonly: this.props.readonly,
            isDebugMode: this.props.isDebugMode,
            defaultConnector: this.props.defaultConnector,
            forceFieldPath: this.props.forceFieldPath,
            domain: this.state.domain,
            update: (domain) => {
                this.state.domain = domain;
                this.props.update(domain, this.props.forceFieldPath);
            },
        };
    }
}
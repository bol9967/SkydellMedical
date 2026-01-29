import { useDebounced } from "@web/core/utils/timing";
import { localization } from "@web/core/l10n/localization";
import {
    onMounted,
    onWillUnmount,
    status,
    useComponent,
    useEffect,
    useExternalListener,
} from "@odoo/owl";

// Configuration for column widths
const MIN_DRAG_DISTANCE = 3
const FIELD_WIDTHS = {
    system: {
        single: { width: 43 },
        openForm: { width: 54 },
        delete: { width: 12 }
    },
    default: {
        minWidth: 80,
        maxWidth: null,
        buffer: 4
    },
    field: {
        boolean: { minWidth: 20, maxWidth: 100 },
        char: { minWidth: 80 },
        date: { width: 90, minContentWidth: 95 },
        datetime: { width: 190, minContentWidth: 145 },
        float: { width: 93, minContentWidth: 20, textAlign: 'right' },
        integer: { width: 71, minContentWidth: 20, textAlign: 'right' },
        many2many: { minWidth: 80 },
        many2one: { minWidth: 80 },
        many2one_reference: { minWidth: 80 },
        monetary: { width: 105, minContentWidth: 20, textAlign: 'right' },
        one2many: { minWidth: 80 },
        reference: { minWidth: 80 },
        selection: { minWidth: 80 },
        text: { minWidth: 80, maxWidth: 1200 },
        html: { minWidth: 80, minContentWidth: 150 }
    },
    content: {
        image: { padding: 10 }
    }
};

const isSpecialColumn = th => ["o_boolean_favorite_cell", "o_priority_cell", "o_list_record_selector"].some(cls => th.classList.contains(cls));
const isSingleColumn = c => !c.hasLabel && ["selection/priority", "boolean/boolean_favorite"].includes(`${c.fieldType}/${c.widget}`);

/**
 * Shared measurement container setup (one-time creation)
 */
let _measurementContainer = null;
function getMeasurementContainer() {
    if (!_measurementContainer) {
        _measurementContainer = document.createElement("div");
        _measurementContainer.id = "o_measure_container";
        _measurementContainer.style.cssText = "position:absolute;visibility:hidden;z-index:-9999;left:-9999px;top:-9999px;";
        document.body.appendChild(_measurementContainer);
    }
    return _measurementContainer;
}

/**
 * Precise measurement of cell content including styles and layout context
 */
function measureElement(element, allowMultiline = false) {
    const container = getMeasurementContainer();
    const clone = element.cloneNode(true);
    const computed = window.getComputedStyle(element);

    container.style.whiteSpace = allowMultiline ? "normal" : "nowrap";
    container.style.lineHeight = computed.lineHeight;

    clone.style.cssText = `
        font: ${computed.font};
        white-space: ${allowMultiline ? "normal" : "nowrap"};
        display: inline-block;
        box-sizing: border-box;
    `;

    container.innerHTML = '';
    container.appendChild(clone);
    const width = clone.getBoundingClientRect().width;

    return Math.ceil(width) + FIELD_WIDTHS.default.buffer;
}

/**
 * Analyze content type and determine optimal width
 */
function analyzeContent(cell, strictMeasure = false) {
    if (!strictMeasure && !cell.textContent.trim()) {
        return FIELD_WIDTHS.default.minWidth;
    }
    if (cell.querySelector('.o_field_boolean')) {
        return FIELD_WIDTHS.field.boolean.width;
    } else if (cell.querySelector('.o_field_monetary, .o_field_float, .o_field_integer')) {
        const fieldType = cell.querySelector('.o_field_monetary') ? 'monetary' :
            cell.querySelector('.o_field_float') ? 'float' : 'integer';
        const config = FIELD_WIDTHS.field[fieldType];
        const width = measureElement(cell);
        return Math.max(width, config.minContentWidth || FIELD_WIDTHS.default.minWidth);
    } else if (cell.matches('.o_field_date, .o_field_datetime')) {
        const fieldType = cell.matches('.o_field_datetime') ? 'datetime' : 'date';
        const config = FIELD_WIDTHS.field[fieldType];
        const width = measureElement(cell);
        return Math.max(width, config.minContentWidth);
    } else if (cell.querySelector('[class*="o_field_html"]')) {
        const width = measureElement(cell);
        return Math.max(width, FIELD_WIDTHS.field.html.minContentWidth);
    }

    if (cell.querySelector('img')) {
        const img = cell.querySelector('img');
        const naturalWidth = img.naturalWidth || img.width;
        return naturalWidth + FIELD_WIDTHS.content.image.padding;
    }

    const allowMultiline = cell.scrollHeight > 36 || cell.offsetHeight > 36;
    const width = measureElement(cell, allowMultiline);
    return strictMeasure ? width : Math.max(width, FIELD_WIDTHS.default.minWidth);
}

/**
 * Get horizontal padding for an element
 */
function getHorizontalPadding(el) {
    if (isSpecialColumn(el)) {
        return 0;
    }
    const { paddingLeft, paddingRight } = getComputedStyle(el);
    return parseFloat(paddingLeft) + parseFloat(paddingRight);
}

/**
 * Get width specifications for a field type
 */
function getFieldWidthSpecs(fieldType) {
    const defaults = FIELD_WIDTHS.default;
    const fieldConfig = FIELD_WIDTHS.field[fieldType] || {};

    if (fieldConfig.width) {
        return {
            minWidth: fieldConfig.width,
            maxWidth: fieldConfig.width
        };
    }

    return {
        minWidth: fieldConfig.minWidth || defaults.minWidth,
        maxWidth: fieldConfig.maxWidth || defaults.maxWidth
    };
}

/**
 * Get width specifications for columns
 */
function getWidthSpecs(columns) {
    return columns.map((column) => {
        let isiColumn = isSingleColumn(column);
        let minWidth, maxWidth, canShrink = (column.type === "field");
        let autofit = (!column.hasLabel && !isiColumn);

        if (column.attrs && column.attrs.width) {
            let parseWidth = parseInt(column.attrs.width);
            if (isiColumn && parseWidth < FIELD_WIDTHS.system.single.width) {
                parseWidth = FIELD_WIDTHS.system.single.width;
            }
            minWidth = maxWidth = parseWidth;
        } else if (isiColumn) {
            minWidth = maxWidth = FIELD_WIDTHS.system.single.width;
            canShrink = false;
        } else {
            let width;
            if (column.type === "field") {
                if (column.field.listViewWidth) {
                    width = column.field.listViewWidth;
                    if (typeof width === "function") {
                        width = width({
                            type: column.fieldType,
                            hasLabel: column.hasLabel,
                            options: column.options,
                        });
                    }
                } else {
                    const specs = getFieldWidthSpecs(column.widget || column.fieldType);
                    minWidth = specs.minWidth;
                    maxWidth = specs.maxWidth;
                }
            } else if (column.type === "widget") {
                width = column.widget.listViewWidth;
            }

            if (width) {
                minWidth = Array.isArray(width) ? width[0] : width;
                maxWidth = Array.isArray(width) ? width[1] : width;
            } else {
                minWidth = FIELD_WIDTHS.default.minWidth;
            }
        }
        return { minWidth, maxWidth, canShrink, autofit };
    });
}

/**
 * Compute ideal widths based on the rules described on top of this file.
 *
 * @params {Element} table
 * @params {Object} state
 * @params {Number} allowedWidth
 * @params {Number[]} startingWidths
 * @returns {Number[]}
 */
function computeWidths(table, state, allowedWidth, startingWidths) {
    const headers = [...table.querySelectorAll("thead th")];
    const columns = state.columns;

    // Compute starting widths
    let columnWidths;
    if (startingWidths) {
        columnWidths = startingWidths.slice();
    } else if (state.isEmpty) {
        // Empty table - uniform distribution
        columnWidths = headers.map(() => allowedWidth / headers.length);
    } else {
        // Let browser calculate initial widths
        table.style.tableLayout = "auto";
        headers.forEach(th => th.style.width = null);
        table.classList.add("o_list_computing_widths");
        columnWidths = headers.map(th => th.getBoundingClientRect().width);
        table.classList.remove("o_list_computing_widths");
    }

    // Apply system column constraints
    const columnOffset = state.hasSelectors ? 1 : 0;
    if (state.hasSelectors) {
        columnWidths[0] = FIELD_WIDTHS.system.single.width * 2;
    }
    if (state.hasOpenFormViewColumn) {
        const index = columnWidths.length - (state.hasActionsColumn ? 2 : 1);
        columnWidths[index] = FIELD_WIDTHS.system.openForm.width;
    }
    if (state.hasActionsColumn) {
        columnWidths[columnWidths.length - 1] = FIELD_WIDTHS.system.delete.width;
    }

    // Apply min/max constraints to data columns
    const columnWidthSpecs = getWidthSpecs(columns);
    for (let columnIndex = 0; columnIndex < columns.length; columnIndex++) {
        const thIndex = columnIndex + columnOffset;
        const { minWidth, maxWidth, autofit } = columnWidthSpecs[columnIndex];
        if (autofit) {
            const columnElements = [...table.tBodies[0].rows]
                .filter(r => r.cells.length === headers.length).slice(0, 10)
                .map(r => r.cells[thIndex]);

            // Analyze max width of all cells
            let maxContentWidth = 0;
            columnElements.forEach(cell => {
                maxContentWidth = Math.max(maxContentWidth, analyzeContent(cell, true));
            });
            columnWidths[thIndex] = maxContentWidth;
        } else {
            columnWidths[thIndex] = Math.max(columnWidths[thIndex], minWidth);
            if (maxWidth) {
                columnWidths[thIndex] = Math.min(columnWidths[thIndex], maxWidth);
            }
        }
    }

    // Redistribute space as needed
    const totalWidth = columnWidths.reduce((tot, width) => tot + width, 0);
    let diff = totalWidth - allowedWidth;

    if (diff >= 1) {
        // Table overflows - shrink columns
        const shrinkableColumns = [];
        let totalAvailableSpace = 0;

        for (let columnIndex = 0; columnIndex < columns.length; columnIndex++) {
            const thIndex = columnIndex + columnOffset;
            const { minWidth, canShrink } = columnWidthSpecs[columnIndex];
            if (columnWidths[thIndex] > minWidth && canShrink) {
                shrinkableColumns.push({ thIndex, minWidth });
                totalAvailableSpace += columnWidths[thIndex] - minWidth;
            }
        }

        if (diff > totalAvailableSpace) {
            // Set all shrinkable columns to minimum
            shrinkableColumns.forEach(({ thIndex, minWidth }) => {
                columnWidths[thIndex] = minWidth;
            });
        } else {
            // Distribute space reduction proportionally
            let remainingColumnsToShrink = shrinkableColumns.length;
            while (diff >= 1 && remainingColumnsToShrink > 0) {
                const colDiff = diff / remainingColumnsToShrink;
                for (const { thIndex, minWidth } of shrinkableColumns) {
                    if (columnWidths[thIndex] === minWidth) continue;

                    const currentWidth = columnWidths[thIndex];
                    const newWidth = Math.max(currentWidth - colDiff, minWidth);
                    diff -= currentWidth - newWidth;
                    columnWidths[thIndex] = newWidth;

                    if (newWidth === minWidth) {
                        remainingColumnsToShrink--;
                    }
                }
            }
        }
    } else if (diff <= -1) {
        // Table has extra space - expand columns
        diff = -diff;
        const expandableColumns = [];

        for (let columnIndex = 0; columnIndex < columns.length; columnIndex++) {
            const thIndex = columnIndex + columnOffset;
            const maxWidth = columnWidthSpecs[columnIndex].maxWidth;
            if (!maxWidth || columnWidths[thIndex] < maxWidth) {
                expandableColumns.push({ thIndex, maxWidth });
            }
        }

        // Distribute space proportionally
        let remainingExpandableColumns = expandableColumns.length;
        while (diff >= 1 && remainingExpandableColumns > 0) {
            const colDiff = diff / remainingExpandableColumns;
            for (const { thIndex, maxWidth } of expandableColumns) {
                const currentWidth = columnWidths[thIndex];
                const newWidth = Math.min(
                    currentWidth + colDiff,
                    maxWidth || Number.MAX_VALUE
                );
                diff -= newWidth - currentWidth;
                columnWidths[thIndex] = newWidth;

                if (maxWidth && newWidth === maxWidth) {
                    remainingExpandableColumns--;
                }
            }
        }

        // If still have space, distribute evenly
        if (diff >= 1) {
            const extraPerColumn = diff / columns.length;
            for (let columnIndex = 0; columnIndex < columns.length; columnIndex++) {
                const thIndex = columnIndex + columnOffset;
                columnWidths[thIndex] += extraPerColumn;
            }
        }
    }

    return columnWidths;
}

function syncColumnWidths(headers, renderer, onlyColumnName = null) {
    return headers.map(th => {
        const width = th.getBoundingClientRect().width - getHorizontalPadding(th);
        const name = th.dataset.name;
        if (!onlyColumnName || name === onlyColumnName) {
            renderer.ue[getLocalStoreKey(renderer, th.dataset.name)] = width;
        }
        return width;
    });
}

function getLocalStoreKey(renderer, name) {
    return `_LCW_${renderer.props.list.resModel}_${renderer.env.config.viewId}_${name}`;
}

/**
 * Clear stored column widths from local renderer state
 */
function clearStoredColumnWidths(renderer) {
    const model = renderer.props.list.resModel;
    const viewId = renderer.env.config.viewId;

    Object.keys(renderer.ue).forEach(key => {
        if (key.startsWith(`_LCW_${model}_${viewId}_`)) {
            delete renderer.ue[key];
        }
    });
}

/**
 * Hook for handling column widths in Odoo list views
 */
export function useOmuxColumnWidths(tableRef, getState) {
    const renderer = useComponent();
    let _resizing = false;
    let columnWidths = null;
    let allowedWidth = 0;
    let hasAlwaysBeenEmpty = true;
    let parentWidthFixed = false;
    let hash;

    /**
     * Calculate and apply column widths
     */
    function forceColumnWidths() {
        const table = tableRef.el;
        const headers = [...table.querySelectorAll("thead th")];
        const state = getState();

        // Check if columns changed
        const nextHash = `${state.columns.map(c => c.id).join("/")}/${headers.length}`;
        if (nextHash !== hash) {
            hash = nextHash;
            unsetWidths();
        }

        // Check if table went from empty to having data
        if (hasAlwaysBeenEmpty && !state.isEmpty) {
            hasAlwaysBeenEmpty = false;
            const rows = table.querySelectorAll(".o_data_row");
            if (rows.length !== 1 || !rows[0].classList.contains("o_selected_row")) {
                unsetWidths();
            }
        }

        // Calculate available width
        const parentPadding = getHorizontalPadding(table.parentNode);
        const cellPaddings = headers.map(th => getHorizontalPadding(th));
        const totalCellPadding = cellPaddings.reduce((total, padding) => total + padding, 0);
        const nextAllowedWidth = table.parentNode.clientWidth - parentPadding - totalCellPadding;
        const allowedWidthDiff = Math.abs(allowedWidth - nextAllowedWidth);
        allowedWidth = nextAllowedWidth;

        // Recompute widths if needed
        if (!columnWidths || allowedWidthDiff > 0) {
            // First compute base widths
            const fallbackWidths = computeWidths(table, state, allowedWidth, columnWidths);

            // Try loading per-column saved widths
            const savedWidths = headers.map((th) => {
                const val = renderer.ue[getLocalStoreKey(renderer, th.dataset.name)];
                return typeof val === "number" ? val : null;
            });

            // Merge
            columnWidths = fallbackWidths.map((w, i) =>
                typeof savedWidths[i] === "number" ? savedWidths[i] : w
            );
        }

        // Apply computed widths
        table.style.tableLayout = "fixed";
        headers.forEach((th, index) => {
            if (columnWidths[index]) {
                const finalWidth = Math.floor(columnWidths[index] + cellPaddings[index]);
                th.style.width = `${finalWidth}px`;
            }
        });
    }

    /**
     * Reset widths for recomputation
     */
    function unsetWidths() {
        columnWidths = null;
        tableRef.el.style.width = null;
        if (parentWidthFixed) {
            tableRef.el.parentElement.style.width = null;
            parentWidthFixed = false;
        }
    }

    /**
     * Handle column resize
     */
    function onStartResize(ev) {
        _resizing = true;
        const table = tableRef.el;
        const th = ev.target.closest("th");

        table.style.width = `${Math.floor(table.getBoundingClientRect().width)}px`;

        // Track initial states
        const initialX = ev.clientX;
        const initialWidth = th.getBoundingClientRect().width;
        const initialTableWidth = table.getBoundingClientRect().width;

        // Fix the width so that if the resize overflows, it doesn't affect the layout of the parent
        if (!table.parentElement.style.width) {
            parentWidthFixed = true;
            table.parentElement.style.width = `${Math.floor(
                table.parentElement.getBoundingClientRect().width
            )}px`;
        }

        // Apply classes to the selected column
        const thPosition = [...th.parentNode.children].indexOf(th);
        const resizingColumnElements = [...table.getElementsByTagName("tr")]
            .filter(tr => tr.children.length === th.parentNode.children.length)
            .map(tr => tr.children[thPosition]);

        resizingColumnElements.forEach(el => {
            el.classList.add("o_column_resizing");
        });

        // Mousemove event : resize header
        const resizeHeader = (ev) => {
            ev.preventDefault();
            ev.stopPropagation();

            let delta = ev.clientX - initialX;
            delta = localization.direction == 'rtl' ? -delta : delta;
            const newWidth = Math.max(10, initialWidth + delta);

            th.style.width = `${Math.floor(newWidth)}px`;
            table.style.width = `${Math.floor(initialTableWidth + (newWidth - initialWidth))}px`;
        };

        // Handle resize completion
        const stopResize = (ev) => {
            // Ignore mouse down as it started the resize
            if (ev.type === "pointerdown" && ev.button === 0) {
                return;
            }

            _resizing = false;
            ev.preventDefault();
            ev.stopPropagation();

            const dragDistance = Math.abs(ev.clientX - initialX);

            // Only store final widths if user dragged enough
            if (dragDistance >= MIN_DRAG_DISTANCE) {
                columnWidths = syncColumnWidths([...table.querySelectorAll("thead th")], renderer, th.dataset.name);
                queueMicrotask(() => {
                    unsetWidths();
                    forceColumnWidths();
                });
            }

            // Cleanup
            resizingColumnElements.forEach(el => {
                el.classList.remove("o_column_resizing");
            });

            // Remove event listeners
            window.removeEventListener("pointermove", resizeHeader);
            ["keydown", "pointerdown", "pointerup"].forEach(eventType => {
                window.removeEventListener(eventType, stopResize);
            });

            // Remove focus to prevent visual oddities
            document.activeElement.blur();
        };

        // Attach event listeners
        window.addEventListener("pointermove", resizeHeader);
        ["keydown", "pointerdown", "pointerup"].forEach(eventType => {
            window.addEventListener(eventType, stopResize);
        });
    }

    /**
     * Force recomputation of column widths
     */
    function resetWidths() {
        unsetWidths();
        forceColumnWidths();
    }

    /**
     * Auto-fit a column based on its content
     */
    function autofit(columnIndex) {
        const table = tableRef.el;
        const headers = [...table.querySelectorAll("thead th")];
        const state = getState();

        // Adjust for selector column
        const adjustedColumnIndex = columnIndex + (state.hasSelectors ? 1 : 0);
        const th = headers[adjustedColumnIndex];
        if (!th) return;

        const column = state.columns[columnIndex];

        // Skip system columns
        if ((state.hasSelectors && adjustedColumnIndex === 0) ||
            (column && isSingleColumn(column)) ||
            (state.hasOpenFormViewColumn && adjustedColumnIndex === headers.length - (state.hasActionsColumn ? 2 : 1)) ||
            (state.hasActionsColumn && adjustedColumnIndex === headers.length - 1)) {
            return;
        }

        // Get column specs and cells
        const columnSpecs = getWidthSpecs(state.columns)[columnIndex];
        const columnElements = [...table.getElementsByTagName("tr")]
            .filter(tr => tr.children.length === headers.length)
            .map(tr => tr.children[adjustedColumnIndex]);

        // Clear existing width styling
        columnElements.forEach(cell => {
            cell.style.width = '';
            cell.style.minWidth = '';
            cell.style.maxWidth = '';
        });

        // Measure optimal width
        let maxContentWidth = 0;
        const cellPadding = getHorizontalPadding(th);

        // Analyze content of all cells
        columnElements.forEach(cell => {
            maxContentWidth = Math.max(maxContentWidth, analyzeContent(cell));
        });

        // Apply constraints
        const finalWidth = Math.max(
            columnSpecs.minWidth,
            Math.min(
                maxContentWidth + cellPadding,
                columnSpecs.maxWidth ? columnSpecs.maxWidth + cellPadding : Infinity
            )
        );

        // Apply width and update state
        th.style.width = `${Math.floor(finalWidth)}px`;
        columnWidths = syncColumnWidths(headers, renderer, th.dataset.name);
        queueMicrotask(() => {
            unsetWidths();
            forceColumnWidths();
        });

        // Update overall table width
        const totalWidth = columnWidths.reduce((sum, width) => sum + width, 0);
        table.style.width = `${Math.floor(totalWidth)}px`;
    }

    // Set up side effects
    if (renderer.constructor.useOmuxColumnWidths) {
        useEffect(forceColumnWidths);
        // Forget computed widths (and potential manual column resize) on window resize
        useExternalListener(window, "resize", resetWidths);
        // Listen to width changes on the parent node of the table, to recompute ideal widths
        // Note: we compute the widths once, directly, and once after parent width stabilization.
        // The first call is only necessary to avoid an annoying flickering when opening form views
        // with an x2many list and a chatter (when it is displayed below the form) as it may happen
        // that the display of chatter messages introduces a vertical scrollbar, thus reducing the
        // available width.
        const component = useComponent();
        let parentWidth;
        const debouncedForceColumnWidths = useDebounced(
            () => {
                if (status(component) !== "destroyed") {
                    forceColumnWidths();
                }
            },
            200,
            { immediate: true, trailing: true }
        );
        const resizeObserver = new ResizeObserver(() => {
            const newParentWidth = tableRef.el.parentNode.clientWidth;
            if (newParentWidth !== parentWidth) {
                parentWidth = newParentWidth;
                debouncedForceColumnWidths();
            }
        });
        onMounted(() => {
            parentWidth = tableRef.el.parentNode.clientWidth;
            resizeObserver.observe(tableRef.el.parentNode);
        });
        onWillUnmount(() => resizeObserver.disconnect());
    }

    // Return API
    return {
        get resizing() { return _resizing; },
        resetColumnWidths: () => { clearStoredColumnWidths(renderer) },
        onStartResize,
        resetWidths,
        autofit,
    };
}
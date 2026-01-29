import { patch } from '@web/core/utils/patch';

import { ControlPanel } from '@web/search/control_panel/control_panel';


patch(ControlPanel.prototype, {

    uInitLayter() { },

    uReloadLayout() {
        this.env.bus.trigger('LYT:RESET');
    },

    uToggleFullScreen() {
        const doc = document;
        const el = doc.documentElement;

        const request = el.requestFullscreen || el.webkitRequestFullscreen || el.mozRequestFullScreen || el.msRequestFullscreen;
        const exit = doc.exitFullscreen || doc.webkitExitFullscreen || doc.mozCancelFullScreen || doc.msExitFullscreen;

        const isFullscreen =
            doc.fullscreenElement ||
            doc.webkitFullscreenElement ||
            doc.mozFullScreenElement ||
            doc.msFullscreenElement;

        if (request && exit) {
            if (isFullscreen) {
                exit.call(doc);
            } else {
                request.call(el);
            }
        } else {
            console.warn("Fullscreen API is not supported on this device.");
            // Optional: show toast or fallback behavior
        }
    },
});

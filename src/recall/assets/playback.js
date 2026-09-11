window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.recall = Object.assign(window.dash_clientside.recall || {}, {
    togglePlayback: function (clicks, active) {
        return clicks ? !active : window.dash_clientside.no_update;
    },

    playbackControls: function (active) {
        return [active ? "fa-solid fa-pause" : "fa-solid fa-play", !active];
    },

    advancePlayback: function (active, tick, min, max, step, value) {
        if (!active) return window.dash_clientside.no_update;
        const next = (Number.isFinite(value) ? value : min) + step;
        return next > max ? min : next;
    },

    renderFrame: function (value, layerIds, manifest, selection, availability) {
        const hidden = (layerIds || []).map(() => 0);
        const empty = [hidden, "", "", "#", "", false];
        if (!selection || !selection.timestamps || !selection.timestamps.length) {
            return empty;
        }
        // Selection can arrive before its new layer tree and manifest.
        if (!manifest || manifest.event_id !== selection.id ||
            manifest.radar !== selection.radar ||
            JSON.stringify(manifest.timestamps) !== JSON.stringify(selection.timestamps)) {
            return [hidden, "", "", "#", "Loading the selected event...", true];
        }
        const index = Math.min(
            Math.max(Number.isFinite(value) ? Math.trunc(value) : 0, 0),
            manifest.frames.length - 1
        );
        const frame = manifest.frames[index];
        const opacities = (layerIds || []).map(id =>
            id.series === manifest.series && id.index === index ? 0.8 : 0
        );
        let warning = "";
        if (availability && availability.error) {
            warning = availability.error;
        } else if (!availability || availability.event_id !== selection.id) {
            warning = "Checking imagery availability...";
        } else if (!availability.available.includes(frame.timestamp_key)) {
            warning = "This scan is not prepared or is unavailable. A blank layer does not " +
                "indicate no precipitation. Use Prepare imagery to retry.";
        }
        return [opacities, frame.label, frame.download_name, frame.download_url,
            warning, Boolean(warning)];
    }
});

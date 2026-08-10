/* Caption overlay: modes + absolute placement from captions.json */

function alignFromEvent(event) {
  if (typeof event.x === "number") {
    if (event.x < 0.38) return "left";
    if (event.x > 0.62) return "right";
    return "center";
  }
  const dir = event.align || event.direction || "CENTER";
  return String(dir).toLowerCase();
}

export function formatCaption(event, mode) {
  if (!event || mode === "off") return null;

  const speaker = event.speaker;
  const text = event.text;
  const align = alignFromEvent(event);

  if (event.kind === "sound") {
    if (mode === "standard" || mode === "speaker") return null;
    if (align === "left") return { align: "left", text: `← ${text}` };
    if (align === "right") return { align: "right", text: `${text} →` };
    return { align: "center", text };
  }

  if (mode === "standard") {
    return { align: "center", text };
  }

  if (mode === "speaker") {
    return { align: "center", text: speaker ? `${speaker}: ${text}` : text };
  }

  const label = speaker ? `${speaker}: ${text}` : text;
  if (align === "left") return { align: "left", text: `← ${label}` };
  if (align === "right") return { align: "right", text: `${label} →` };
  return { align: "center", text: label };
}

export function createCaptionController({ overlayEl, modeSelect }) {
  let track = null;
  let mode = modeSelect?.value || "spatial";

  function setTrack(next) {
    track = next;
    render(0);
  }

  function setMode(next) {
    mode = next;
  }

  function activeEvents(t) {
    if (!track?.events?.length) return [];
    return track.events.filter((e) => t >= e.start && t <= e.end);
  }

  function render(t) {
    if (!overlayEl) return;
    overlayEl.innerHTML = "";
    if (mode === "off" || !track) return;

    const events = activeEvents(t);
    const visible =
      mode === "full"
        ? events
        : events.filter((e) => e.kind === "speech").slice(0, 1);

    const usePlacement = mode === "spatial" || mode === "full";

    visible.forEach((event) => {
      const renderMode = mode === "full" ? "spatial" : mode;
      const formatted = formatCaption(event, renderMode);
      if (!formatted) return;
      const el = document.createElement("div");
      el.className = `caption-line align-${formatted.align} kind-${event.kind || "speech"}`;
      el.textContent = formatted.text;

      if (usePlacement && typeof event.x === "number") {
        el.classList.add("placed");
        const y = typeof event.y === "number" ? event.y : 0.78;
        // Keep captions inside the frame.
        const x = Math.min(0.92, Math.max(0.08, event.x));
        const clampedY = Math.min(0.9, Math.max(0.06, y));
        el.style.left = `${(x * 100).toFixed(1)}%`;
        el.style.top = `${(clampedY * 100).toFixed(1)}%`;
        el.style.transform =
          formatted.align === "left"
            ? "translate(0, 0)"
            : formatted.align === "right"
              ? "translate(-100%, 0)"
              : "translate(-50%, 0)";
      }

      overlayEl.appendChild(el);
    });
  }

  return { setTrack, setMode, render, getTrack: () => track };
}

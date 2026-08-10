import { createAbrController } from "./abr.js";
import { createCaptionController } from "./captions.js";
import { createMetrics } from "./metrics.js";

const videoEl = document.getElementById("video");
const videoSelect = document.getElementById("videoSelect");
const abrSelect = document.getElementById("abrSelect");
const qualitySelect = document.getElementById("qualitySelect");
const traceSelect = document.getElementById("traceSelect");
const captionMode = document.getElementById("captionMode");
const reloadBtn = document.getElementById("reloadBtn");
const exportBtn = document.getElementById("exportBtn");
const logEl = document.getElementById("log");
const captionOverlay = document.getElementById("captionOverlay");

const captions = createCaptionController({
  overlayEl: captionOverlay,
  modeSelect: captionMode,
});

const els = {
  quality: document.getElementById("tQuality"),
  buffer: document.getElementById("tBuffer"),
  throughput: document.getElementById("tThroughput"),
  simBw: document.getElementById("tSimBw"),
  volatility: document.getElementById("tVol"),
  position: document.getElementById("tPosition"),
  segment: document.getElementById("tSegment"),
  download: document.getElementById("tDownload"),
  state: document.getElementById("tState"),
  startup: document.getElementById("mStartup"),
  rebuffer: document.getElementById("mRebuffer"),
  switches: document.getElementById("mSwitches"),
  bitrate: document.getElementById("mBitrate"),
  abr: document.getElementById("mAbr"),
  trace: document.getElementById("mTrace"),
};

let hls = null;
let abr = createAbrController(abrSelect.value);
let metrics = createMetrics();
let ewmaBps = 0;
const EWMA_ALPHA = 0.3;
const recentThroughputs = [];
let lastFragStats = { bwEstimate: 0, loading: null, lastDownload: null };
let simBwMbps = null;

function throughputStats() {
  if (!recentThroughputs.length) {
    return { mean: ewmaBps, std: 0, trend: 0, cv: 0 };
  }
  const mean =
    recentThroughputs.reduce((a, b) => a + b, 0) / recentThroughputs.length;
  let std = 0;
  if (recentThroughputs.length > 1) {
    const varSum = recentThroughputs.reduce(
      (a, b) => a + (b - mean) ** 2,
      0
    );
    std = Math.sqrt(varSum / (recentThroughputs.length - 1));
  }
  const half = Math.max(1, Math.floor(recentThroughputs.length / 2));
  const older =
    recentThroughputs.slice(0, half).reduce((a, b) => a + b, 0) / half;
  const newer =
    recentThroughputs.slice(-half).reduce((a, b) => a + b, 0) / half;
  const trend = older > 0 ? (newer - older) / older : 0;
  const cv = mean > 0 ? std / mean : 0;
  return { mean: ewmaBps || mean, std, trend, cv };
}

function log(message) {
  const ts = new Date().toISOString().slice(11, 19);
  logEl.textContent = `[${ts}] ${message}\n` + logEl.textContent;
}

function formatMbps(bps) {
  if (!bps || !Number.isFinite(bps)) return "—";
  return `${(bps / 1e6).toFixed(2)} Mbps`;
}

function formatSeconds(s) {
  if (!Number.isFinite(s)) return "—";
  return `${s.toFixed(1)} s`;
}

function bufferAhead(video) {
  const { currentTime, buffered } = video;
  for (let i = 0; i < buffered.length; i += 1) {
    if (currentTime >= buffered.start(i) && currentTime <= buffered.end(i)) {
      return buffered.end(i) - currentTime;
    }
  }
  return 0;
}

function currentLevelLabel() {
  if (!hls || !hls.levels?.length) return "—";
  const idx = hls.currentLevel >= 0 ? hls.currentLevel : hls.loadLevel;
  if (idx < 0 || !hls.levels[idx]) return "—";
  const level = hls.levels[idx];
  const h = level.height || "?";
  const br = level.bitrate ? `${Math.round(level.bitrate / 1000)} kbps` : "";
  return `${h}p${br ? ` (${br})` : ""}`;
}

function updateTelemetry() {
  const buf = bufferAhead(videoEl);
  els.quality.textContent = currentLevelLabel();
  els.buffer.textContent = formatSeconds(buf);
  els.throughput.textContent = formatMbps(ewmaBps || lastFragStats.bwEstimate);
  els.simBw.textContent =
    simBwMbps != null ? `${Number(simBwMbps).toFixed(2)} Mbps` : "off";
  const { cv } = throughputStats();
  els.volatility.textContent = Number.isFinite(cv) ? cv.toFixed(2) : "—";
  els.position.textContent = formatSeconds(videoEl.currentTime);
  els.segment.textContent =
    lastFragStats.loading != null ? String(lastFragStats.loading) : "—";
  els.download.textContent = lastFragStats.lastDownload
    ? `${lastFragStats.lastDownload.toFixed(0)} ms`
    : "—";

  if (videoEl.seeking) els.state.textContent = "seeking";
  else if (videoEl.paused) els.state.textContent = "paused";
  else if (buf < 0.25 && !videoEl.paused && metrics.firstFrameAt) {
    els.state.textContent = "rebuffering";
  } else els.state.textContent = "playing";

  const summary = metrics.summary();
  els.startup.textContent =
    summary.startupLatencyMs != null
      ? `${Math.round(summary.startupLatencyMs)} ms`
      : "—";
  els.rebuffer.textContent = `${summary.rebufferEvents} / ${summary.rebufferMs} ms`;
  els.switches.textContent = String(summary.qualitySwitches);
  els.bitrate.textContent = summary.avgBitrateKbps
    ? `${summary.avgBitrateKbps} kbps`
    : "—";
  els.abr.textContent = abrSelect.value;
  els.trace.textContent = traceSelect.value || "none";
}

function populateQualities(levels) {
  const previous = qualitySelect.value;
  qualitySelect.innerHTML = "";
  levels.forEach((level, index) => {
    const opt = document.createElement("option");
    opt.value = String(index);
    const kbps = Math.round(level.bitrate / 1000);
    opt.textContent = `${level.height}p · ${kbps} kbps`;
    qualitySelect.appendChild(opt);
  });
  if ([...qualitySelect.options].some((o) => o.value === previous)) {
    qualitySelect.value = previous;
  } else if (levels.length) {
    qualitySelect.value = "0";
  }
  qualitySelect.disabled = abrSelect.value !== "fixed";
}

function applyAbrDecision() {
  if (!hls || !hls.levels?.length) return;
  if (abrSelect.value === "hls") {
    // Re-enable native ABR
    if (hls.autoLevelEnabled === false) {
      hls.currentLevel = -1;
    }
    return;
  }

  const stats = throughputStats();
  const decision = abr.decide({
    levels: hls.levels,
    currentLevel: hls.loadLevel >= 0 ? hls.loadLevel : hls.currentLevel,
    bufferSeconds: bufferAhead(videoEl),
    throughputBps: stats.mean,
    throughputStdBps: stats.std,
    throughputTrend: stats.trend,
    segmentDuration: hls.levels[0]?.details?.targetduration || 2,
  });

  if (decision < 0) return;
  if (hls.loadLevel !== decision) {
    hls.loadLevel = decision;
    hls.nextLevel = decision;
  }
}

function destroyPlayer() {
  if (hls) {
    hls.destroy();
    hls = null;
  }
}

async function applyTrace(traceName, { reset = true } = {}) {
  if (!traceName) {
    const res = await fetch("/api/throttle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: false, reset: true }),
    });
    const status = await res.json();
    simBwMbps = null;
    log("Throttle disabled");
    return status;
  }

  const res = await fetch("/api/throttle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      enabled: true,
      trace: traceName,
      loop: true,
      reset,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to set throttle");
  }
  const status = await res.json();
  simBwMbps = status.current_mbps;
  log(`Throttle → ${traceName} (${status.sample_count}s trace)`);
  return status;
}

async function pollThrottleStatus() {
  try {
    const res = await fetch("/api/throttle");
    const status = await res.json();
    simBwMbps = status.enabled ? status.current_mbps : null;
  } catch {
    /* ignore */
  }
}

async function loadCaptions(name) {
  try {
    const res = await fetch(`/api/videos/${name}/captions.json`);
    if (!res.ok) {
      captions.setTrack(null);
      log(`No captions for ${name}`);
      return;
    }
    const track = await res.json();
    captions.setTrack(track);
    captions.setMode(captionMode.value);
    log(`Captions loaded (${track.events?.length || 0} events)`);
  } catch (err) {
    captions.setTrack(null);
    log(`Caption load failed: ${err.message}`);
  }
}

async function loadVideo(name) {
  destroyPlayer();
  ewmaBps = 0;
  recentThroughputs.length = 0;
  lastFragStats = { bwEstimate: 0, loading: null, lastDownload: null };
  abr = createAbrController(abrSelect.value);
  abr.setFixedLevel(Number(qualitySelect.value) || 0);

  metrics = createMetrics();
  metrics.markStart({
    abr: abrSelect.value,
    trace: traceSelect.value || null,
    video: name,
  });

  await loadCaptions(name);

  const src = `/hls/${name}/master.m3u8`;
  log(`Loading ${src} · ABR=${abrSelect.value}`);

  if (!Hls.isSupported()) {
    log("HLS not supported in this browser");
    els.state.textContent = "unsupported";
    return;
  }

  const useNativeAbr = abrSelect.value === "hls";
  hls = new Hls({
    enableWorker: true,
    lowLatencyMode: false,
    startLevel: useNativeAbr ? -1 : 0,
    autoStartLoad: true,
  });

  hls.loadSource(src);
  hls.attachMedia(videoEl);

  hls.on(Hls.Events.MANIFEST_PARSED, (_event, data) => {
    populateQualities(data.levels);
    log(`Manifest parsed: ${data.levels.length} levels`);
    if (!useNativeAbr) {
      hls.loadLevel = 0;
      hls.nextLevel = 0;
      applyAbrDecision();
    }
    videoEl.play().catch(() => log("Autoplay blocked — press play"));
  });

  hls.on(Hls.Events.LEVEL_SWITCHED, (_event, data) => {
    const level = hls.levels[data.level];
    metrics.noteLevel(data.level, level?.bitrate);
    log(`Quality → ${level?.height}p (level ${data.level})`);
  });

  hls.on(Hls.Events.FRAG_LOADING, (_event, data) => {
    lastFragStats.loading = data.frag?.sn;
  });

  hls.on(Hls.Events.FRAG_LOADED, (_event, data) => {
    const frag = data.frag;
    const stats = frag?.stats;
    let sampleBps = 0;
    if (stats) {
      const downloadMs = stats.loading.end - stats.loading.start;
      lastFragStats.lastDownload = downloadMs;
      const bytes = stats.total || stats.loaded || 0;
      if (downloadMs > 0 && bytes > 0) {
        sampleBps = (bytes * 8) / (downloadMs / 1000);
        ewmaBps = ewmaBps
          ? EWMA_ALPHA * sampleBps + (1 - EWMA_ALPHA) * ewmaBps
          : sampleBps;
        recentThroughputs.push(sampleBps);
        if (recentThroughputs.length > 8) recentThroughputs.shift();
        lastFragStats.bwEstimate = ewmaBps;
        metrics.noteSegment({
          sn: frag.sn,
          level: frag.level,
          bytes,
          downloadMs,
          throughputBps: sampleBps,
        });
      }
    }

    applyAbrDecision();
  });

  hls.on(Hls.Events.ERROR, (_event, data) => {
    log(`Error: ${data.type} / ${data.details}`);
    if (data.fatal) els.state.textContent = "error";
  });
}

async function init() {
  const [videosRes, tracesRes] = await Promise.all([
    fetch("/api/videos"),
    fetch("/api/traces"),
  ]);
  const videosData = await videosRes.json();
  const tracesData = await tracesRes.json();

  const videos = videosData.videos || [];
  videoSelect.innerHTML = "";
  if (!videos.length) {
    const opt = document.createElement("option");
    opt.textContent = "No packaged videos";
    videoSelect.appendChild(opt);
    log("No videos found. Run package_hls.py first.");
    return;
  }
  videos.forEach((v) => {
    const opt = document.createElement("option");
    opt.value = v.name;
    opt.textContent = v.name;
    videoSelect.appendChild(opt);
  });

  traceSelect.innerHTML = "";
  const none = document.createElement("option");
  none.value = "";
  none.textContent = "None (unlimited)";
  traceSelect.appendChild(none);
  (tracesData.traces || []).forEach((t) => {
    const opt = document.createElement("option");
    opt.value = t.name;
    opt.textContent = `${t.name} (${t.min_mbps}–${t.max_mbps} Mbps)`;
    traceSelect.appendChild(opt);
  });

  // Prefer dialogue demo when available
  const preferred =
    videos.find((v) => v.name === "dialogue_demo") || videos[0];
  videoSelect.value = preferred.name;

  // Default demo: volatile + risk-aware
  if ([...traceSelect.options].some((o) => o.value === "volatile")) {
    traceSelect.value = "volatile";
  }
  await applyTrace(traceSelect.value);
  await loadVideo(preferred.name);
}

videoSelect.addEventListener("change", async () => {
  await applyTrace(traceSelect.value, { reset: true });
  await loadVideo(videoSelect.value);
});

abrSelect.addEventListener("change", async () => {
  qualitySelect.disabled = abrSelect.value !== "fixed";
  abr = createAbrController(abrSelect.value);
  abr.setFixedLevel(Number(qualitySelect.value) || 0);
  log(`ABR → ${abrSelect.value}`);
  if (videoSelect.value) await loadVideo(videoSelect.value);
});

qualitySelect.addEventListener("change", () => {
  abr.setFixedLevel(Number(qualitySelect.value) || 0);
  if (abrSelect.value === "fixed") applyAbrDecision();
});

captionMode.addEventListener("change", () => {
  captions.setMode(captionMode.value);
  captions.render(videoEl.currentTime || 0);
  log(`Captions → ${captionMode.value}`);
});

traceSelect.addEventListener("change", async () => {
  await applyTrace(traceSelect.value, { reset: true });
  if (videoSelect.value) await loadVideo(videoSelect.value);
});

reloadBtn.addEventListener("click", async () => {
  await applyTrace(traceSelect.value, { reset: true });
  if (videoSelect.value) await loadVideo(videoSelect.value);
});

exportBtn.addEventListener("click", () => {
  const payload = {
    summary: metrics.summary(),
    segments: metrics.segmentDownloads,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `metrics-${abrSelect.value}-${traceSelect.value || "none"}-${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(url);
  log("Exported metrics JSON");
});

videoEl.addEventListener("playing", () => metrics.markPlaying());
videoEl.addEventListener("waiting", () => metrics.markWaiting());
videoEl.addEventListener("timeupdate", () => {
  captions.render(videoEl.currentTime || 0);
});

setInterval(updateTelemetry, 250);
setInterval(() => captions.render(videoEl.currentTime || 0), 200);
setInterval(pollThrottleStatus, 1000);

init().catch((err) => {
  log(`Init failed: ${err.message}`);
});

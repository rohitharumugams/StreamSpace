/**
 * Session metrics for ABR evaluation.
 */

export function createMetrics() {
  return {
    startedAt: null,
    firstFrameAt: null,
    startupLatencyMs: null,
    qualitySwitches: 0,
    lastLevel: null,
    rebufferEvents: 0,
    rebufferMs: 0,
    _rebufferStartedAt: null,
    bitrateSamples: [],
    segmentDownloads: [],
    abr: null,
    trace: null,
    video: null,

    markStart(meta = {}) {
      this.startedAt = performance.now();
      this.firstFrameAt = null;
      this.startupLatencyMs = null;
      this.qualitySwitches = 0;
      this.lastLevel = null;
      this.rebufferEvents = 0;
      this.rebufferMs = 0;
      this._rebufferStartedAt = null;
      this.bitrateSamples = [];
      this.segmentDownloads = [];
      this.abr = meta.abr ?? null;
      this.trace = meta.trace ?? null;
      this.video = meta.video ?? null;
    },

    markPlaying() {
      if (this.firstFrameAt == null && this.startedAt != null) {
        this.firstFrameAt = performance.now();
        this.startupLatencyMs = this.firstFrameAt - this.startedAt;
      }
      if (this._rebufferStartedAt != null) {
        this.rebufferMs += performance.now() - this._rebufferStartedAt;
        this._rebufferStartedAt = null;
      }
    },

    markWaiting() {
      if (this.firstFrameAt == null) return; // ignore initial startup stall
      if (this._rebufferStartedAt == null) {
        this._rebufferStartedAt = performance.now();
        this.rebufferEvents += 1;
      }
    },

    noteLevel(level, bitrate) {
      if (this.lastLevel != null && level !== this.lastLevel && level >= 0) {
        this.qualitySwitches += 1;
      }
      if (level >= 0) this.lastLevel = level;
      if (bitrate) this.bitrateSamples.push(bitrate);
    },

    noteSegment({ sn, level, bytes, downloadMs, throughputBps }) {
      this.segmentDownloads.push({
        t: performance.now(),
        sn,
        level,
        bytes,
        downloadMs,
        throughputBps,
      });
    },

    summary() {
      const bitrates = this.bitrateSamples;
      const avgBitrate = bitrates.length
        ? bitrates.reduce((a, b) => a + b, 0) / bitrates.length
        : 0;
      return {
        video: this.video,
        abr: this.abr,
        trace: this.trace,
        startupLatencyMs: this.startupLatencyMs,
        qualitySwitches: this.qualitySwitches,
        rebufferEvents: this.rebufferEvents,
        rebufferMs: Math.round(this.rebufferMs),
        avgBitrateBps: Math.round(avgBitrate),
        avgBitrateKbps: Math.round(avgBitrate / 1000),
        segmentsDownloaded: this.segmentDownloads.length,
        durationMs:
          this.startedAt != null ? Math.round(performance.now() - this.startedAt) : 0,
      };
    },
  };
}

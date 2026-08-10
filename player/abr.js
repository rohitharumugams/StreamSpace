/**
 * ABR controllers for hls.js (manual level selection).
 *
 * Each decide() returns a level index into hls.levels.
 */

export function createAbrController(name) {
  switch (name) {
    case "throughput":
      return new ThroughputAbr();
    case "buffer":
      return new BufferAbr();
    case "hybrid":
      return new HybridAbr();
    case "risk":
      return new RiskAwareAbr();
    case "fixed":
      return new FixedAbr();
    case "hls":
    default:
      return new HlsNativeAbr();
  }
}

class BaseAbr {
  constructor(name) {
    this.name = name;
    this.fixedLevel = 0;
  }

  reset() {}

  setFixedLevel(level) {
    this.fixedLevel = level;
  }

  /**
   * @param {object} ctx
   * @param {Array<{bitrate:number,height:number}>} ctx.levels
   * @param {number} ctx.currentLevel
   * @param {number} ctx.bufferSeconds
   * @param {number} ctx.throughputBps  EWMA estimate
   * @param {number} ctx.throughputStdBps
   * @param {number} ctx.throughputTrend
   * @param {number} ctx.segmentDuration
   */
  decide(ctx) {
    return ctx.currentLevel >= 0 ? ctx.currentLevel : 0;
  }
}

class HlsNativeAbr extends BaseAbr {
  constructor() {
    super("hls");
  }

  decide() {
    return -1; // tell player to leave control to hls.js
  }
}

class FixedAbr extends BaseAbr {
  constructor() {
    super("fixed");
  }

  decide(ctx) {
    const max = Math.max(0, ctx.levels.length - 1);
    return Math.min(Math.max(0, this.fixedLevel), max);
  }
}

class ThroughputAbr extends BaseAbr {
  constructor() {
    super("throughput");
    this.safety = 0.8;
  }

  decide(ctx) {
    const { levels, throughputBps, currentLevel } = ctx;
    if (!levels.length) return 0;
    if (!throughputBps || throughputBps <= 0) {
      return currentLevel >= 0 ? currentLevel : 0;
    }

    const budget = throughputBps * this.safety;
    let chosen = 0;
    for (let i = 0; i < levels.length; i += 1) {
      if (levels[i].bitrate <= budget) chosen = i;
    }
    return chosen;
  }
}

class BufferAbr extends BaseAbr {
  constructor() {
    super("buffer");
    this.low = 4;
    this.high = 12;
  }

  decide(ctx) {
    const { levels, bufferSeconds, currentLevel } = ctx;
    if (!levels.length) return 0;
    let level = currentLevel >= 0 ? currentLevel : 0;

    if (bufferSeconds < this.low) {
      level = Math.max(0, level - 1);
    } else if (bufferSeconds > this.high) {
      level = Math.min(levels.length - 1, level + 1);
    }
    return level;
  }
}

class HybridAbr extends BaseAbr {
  constructor() {
    super("hybrid");
    this.safety = 0.75;
    this.low = 5;
    this.high = 15;
    this.reservoir = 8;
  }

  decide(ctx) {
    const { levels, bufferSeconds, currentLevel } = ctx;
    if (!levels.length) return 0;

    let level = currentLevel >= 0 ? currentLevel : 0;
    const throughputPick = new ThroughputAbr();
    throughputPick.safety = this.safety;
    const thruLevel = throughputPick.decide(ctx);

    if (bufferSeconds < 2) {
      level = 0;
    } else if (bufferSeconds < this.low) {
      level = Math.min(thruLevel, Math.max(0, level - 1));
    } else if (bufferSeconds < this.reservoir) {
      level = Math.min(level, thruLevel);
    } else if (bufferSeconds > this.high) {
      level = thruLevel > level ? level + 1 : thruLevel;
    } else {
      level = thruLevel;
    }

    return Math.max(0, Math.min(levels.length - 1, level));
  }
}

class RiskAwareAbr extends BaseAbr {
  constructor() {
    super("risk");
    this.baseSafety = 0.8;
    this.lowBuffer = 5;
    this.highBuffer = 14;
    this.riskHorizon = 1.15;
    this.hold = 0;
  }

  volatility(ctx) {
    if (!ctx.throughputBps || ctx.throughputBps <= 0) return 1;
    return Math.max(0, (ctx.throughputStdBps || 0) / ctx.throughputBps);
  }

  conservativeBps(ctx, cv) {
    const mean = ctx.throughputBps;
    if (!mean || mean <= 0) return 0;
    const std = ctx.throughputStdBps || 0;
    let z = 0.4 + 1.2 * Math.min(cv, 1.0);
    if (ctx.bufferSeconds < this.lowBuffer) z += 0.5;
    if ((ctx.throughputTrend || 0) < -0.15) z += 0.4;
    const floor = mean * (cv > 0.5 ? 0.35 : 0.45);
    return Math.max(mean - z * std, floor);
  }

  safety(ctx, cv) {
    let safety = this.baseSafety;
    if (cv > 0.5) safety = 0.55;
    else if (cv > 0.3) safety = 0.65;
    else if (cv > 0.15) safety = 0.72;
    if (ctx.bufferSeconds < 3) safety *= 0.7;
    else if (ctx.bufferSeconds < this.lowBuffer) safety *= 0.85;
    else if (ctx.bufferSeconds > this.highBuffer && cv < 0.2) {
      safety = Math.min(0.9, safety + 0.08);
    }
    return safety;
  }

  underrunRisk(bitrate, conservativeBps, bufferSeconds, segmentDuration) {
    if (!conservativeBps || conservativeBps <= 0) return 10;
    const estDownload = (bitrate * segmentDuration) / conservativeBps;
    return estDownload / Math.max(bufferSeconds, 0.05);
  }

  targetLevel(ctx, cv) {
    const conservative = this.conservativeBps(ctx, cv);
    const budget = conservative * this.safety(ctx, cv);
    let chosen = 0;
    for (let i = 0; i < ctx.levels.length; i += 1) {
      if (ctx.levels[i].bitrate > budget) break;
      const risk = this.underrunRisk(
        ctx.levels[i].bitrate,
        conservative,
        ctx.bufferSeconds,
        ctx.segmentDuration || 2
      );
      const limit = ctx.bufferSeconds >= this.lowBuffer ? this.riskHorizon : 0.9;
      if (risk <= limit) chosen = i;
    }
    return chosen;
  }

  decide(ctx) {
    const { levels, currentLevel, bufferSeconds, throughputBps, segmentDuration } =
      ctx;
    if (!levels.length) return 0;
    const current = currentLevel >= 0 ? currentLevel : 0;
    if (!throughputBps || throughputBps <= 0) return current;

    const cv = this.volatility(ctx);
    const target = this.targetLevel(ctx, cv);
    const conservative = this.conservativeBps(ctx, cv);
    const seg = segmentDuration || 2;

    if (bufferSeconds < 2) {
      this.hold = 2;
      return 0;
    }
    if (bufferSeconds < this.lowBuffer) {
      this.hold = Math.max(this.hold, 1);
      return Math.min(target, current, Math.max(0, current - 1));
    }

    const currentBitrate = levels[current].bitrate;
    const currentRisk = this.underrunRisk(
      currentBitrate,
      conservative,
      bufferSeconds,
      seg
    );
    const safety = this.safety(ctx, cv);
    const affordable = currentBitrate <= conservative * safety * 1.05;
    const safeEnough =
      currentRisk <= this.riskHorizon * (cv > 0.35 ? 1.15 : 1.35);

    if (target < current) {
      if (affordable && safeEnough && bufferSeconds >= this.lowBuffer) {
        if (this.hold > 0) this.hold -= 1;
        return current;
      }
      let chosen =
        currentBitrate > conservative * safety * 1.35
          ? Math.max(target, current - 2)
          : current - 1;
      this.hold = 2;
      return Math.max(0, chosen);
    }

    if (target > current && affordable && safeEnough) {
      let canUp =
        bufferSeconds >= 10 &&
        (ctx.throughputTrend || 0) >= -0.1 &&
        this.hold <= 0 &&
        currentRisk <= 0.95;
      if (cv > 0.55) canUp = canUp && bufferSeconds >= this.highBuffer;
      if (canUp) {
        this.hold = cv < 0.3 ? 2 : 4;
        return Math.min(levels.length - 1, current + 1);
      }
      if (this.hold > 0) this.hold -= 1;
      return current;
    }

    if (this.hold > 0) this.hold -= 1;
    return current;
  }
}

import { createCaptionController } from "./captions.js";

const intro = document.getElementById("intro");
const run = document.getElementById("run");
const done = document.getElementById("done");
const startBtn = document.getElementById("startBtn");
const participantId = document.getElementById("participantId");
const videoEl = document.getElementById("video");
const overlay = document.getElementById("captionOverlay");
const trialLabel = document.getElementById("trialLabel");
const conditionLabel = document.getElementById("conditionLabel");
const answerForm = document.getElementById("answerForm");
const replayBtn = document.getElementById("replayBtn");
const summaryEl = document.getElementById("summary");
const downloadBtn = document.getElementById("downloadBtn");

const captions = createCaptionController({
  overlayEl: overlay,
  modeSelect: null,
});

let hls = null;
let trials = [];
let index = 0;
let answers = [];
let session = null;

function shuffle(list) {
  const arr = [...list];
  for (let i = arr.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

async function loadSession() {
  const res = await fetch("/api/study/trials?video=dialogue_demo");
  if (!res.ok) throw new Error("Could not load study trials");
  const data = await res.json();
  captions.setTrack(data.captions);

  // Build paired trials: each cue once in standard and once in spatial, shuffled.
  const base = data.trials || [];
  const paired = [];
  base.forEach((trial, i) => {
    paired.push({ ...trial, condition: i % 2 === 0 ? "standard" : "spatial", pair: i });
    paired.push({
      ...trial,
      condition: i % 2 === 0 ? "spatial" : "standard",
      pair: i,
    });
  });
  // Keep at most 8 trials for a short study (4 cues × 2 conditions)
  trials = shuffle(paired).slice(0, 8);
  session = {
    participant: participantId.value.trim() || `anon-${Date.now()}`,
    video: data.video,
    startedAt: new Date().toISOString(),
    trials: [],
  };

  destroyPlayer();
  const src = `/hls/${data.video}/master.m3u8`;
  if (Hls.isSupported()) {
    hls = new Hls({ startLevel: 0, autoStartLoad: true });
    hls.loadSource(src);
    hls.attachMedia(videoEl);
  } else {
    videoEl.src = src;
  }
  videoEl.muted = true;
}

function destroyPlayer() {
  if (hls) {
    hls.destroy();
    hls = null;
  }
}

function playCurrent() {
  const trial = trials[index];
  if (!trial) return;
  trialLabel.textContent = `Trial ${index + 1} / ${trials.length}`;
  conditionLabel.textContent = `Condition: ${trial.condition}`;
  captions.setMode(trial.condition);
  answerForm.reset();

  const start = Math.max(0, trial.start - 0.15);
  const end = trial.end + 0.35;

  const onTime = () => {
    captions.render(videoEl.currentTime || 0);
    if (videoEl.currentTime >= end) {
      videoEl.pause();
      videoEl.removeEventListener("timeupdate", onTime);
    }
  };

  videoEl.removeEventListener("timeupdate", onTime);
  videoEl.addEventListener("timeupdate", onTime);
  videoEl.currentTime = start;
  videoEl.play().catch(() => {});
}

function finish() {
  run.classList.add("hidden");
  done.classList.remove("hidden");

  const byCondition = { standard: [], spatial: [] };
  answers.forEach((a) => byCondition[a.condition]?.push(a));

  function score(list) {
    if (!list.length) return { n: 0, speaker: 0, side: 0 };
    const speaker = list.filter((a) => a.speaker_correct).length / list.length;
    const side = list.filter((a) => a.side_correct).length / list.length;
    return {
      n: list.length,
      speaker: Math.round(speaker * 1000) / 10,
      side: Math.round(side * 1000) / 10,
    };
  }

  const std = score(byCondition.standard);
  const spa = score(byCondition.spatial);
  session.finishedAt = new Date().toISOString();
  session.summary = {
    standard: std,
    spatial: spa,
  };
  session.trials = answers;

  summaryEl.textContent = [
    `Participant: ${session.participant}`,
    `Standard  — speaker ${std.speaker}%  side ${std.side}%  (n=${std.n})`,
    `Spatial   — speaker ${spa.speaker}%  side ${spa.side}%  (n=${spa.n})`,
  ].join("\n");

  fetch("/api/study/results", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(session),
  }).catch(() => {});
}

startBtn.addEventListener("click", async () => {
  try {
    await loadSession();
    intro.classList.add("hidden");
    run.classList.remove("hidden");
    index = 0;
    answers = [];
    // wait briefly for media
    setTimeout(playCurrent, 400);
  } catch (err) {
    alert(err.message);
  }
});

replayBtn.addEventListener("click", () => playCurrent());

answerForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const trial = trials[index];
  const data = new FormData(answerForm);
  const speaker = String(data.get("speaker") || "");
  const side = String(data.get("side") || "");
  answers.push({
    index,
    condition: trial.condition,
    text: trial.text,
    gt_speaker: trial.speaker,
    gt_side: trial.side,
    response_speaker: speaker,
    response_side: side,
    speaker_correct: speaker === trial.speaker,
    side_correct: side === trial.side,
  });
  index += 1;
  if (index >= trials.length) finish();
  else playCurrent();
});

downloadBtn.addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(session, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `study-${session?.participant || "anon"}.json`;
  a.click();
  URL.revokeObjectURL(url);
});

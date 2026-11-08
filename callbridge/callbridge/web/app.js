/* CallBridge – interfaz de revisión. JS sin dependencias. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const h = (tag, props = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k in el) el[k] = v;
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
};

const RULER_H = 24, WAVE_H = 46, LANE_H = 40, ADD_H = 36, MAX_PPS = 300;

const S = {
  p: null, peaks: null, pps: 20, sel: null, history: [], future: [],
  dirty: false, saveTimer: null, saving: null, poll: null, lastJobs: {},
  chan: "both", stopAt: null, audioCtx: null, gains: null, raf: null, lastNow: -1,
  editingText: false,
};

const audio = $("#audio");
const viewport = $("#viewport");
const inner = $("#inner");

// ------------------------------------------------------------------ utilidades
function fmt(t, ms = false) {
  t = Math.max(0, t || 0);
  const hh = Math.floor(t / 3600), mm = Math.floor((t % 3600) / 60), ss = Math.floor(t % 60);
  const base = (hh ? hh + ":" + String(mm).padStart(2, "0") : String(mm).padStart(2, "0")) + ":" + String(ss).padStart(2, "0");
  return ms ? base + "." + String(Math.floor((t % 1) * 10)) : base;
}
const r3 = (x) => Math.round(x * 1000) / 1000;
const norm = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const uid = () => "s" + Math.random().toString(16).slice(2, 12);

async function api(method, url, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  let data = null;
  try { data = await r.json(); } catch { /* sin cuerpo */ }
  if (!r.ok) throw new Error((data && data.error) || `Error ${r.status}`);
  return data;
}

let toastTimer;
function toast(msg, action) {
  const t = $("#toast");
  t.replaceChildren(h("span", {}, msg));
  if (action) t.append(h("button", { onclick: () => { action.fn(); t.hidden = true; } }, action.label));
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), action ? 8000 : 3500);
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); }
  catch {
    const ta = h("textarea", { value: text });
    document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
  toast("Copiado al portapapeles");
}

// ------------------------------------------------------------------ modelo
const segs = () => S.p.segments;
const spk = (id) => S.p.speakers.find((s) => s.id === id);
const label = (id) => (spk(id) || {}).label || id;
const color = (id) => (spk(id) || {}).color || "#888";
const selSeg = () => S.p && S.p.segments.find((s) => s.id === S.sel);
const sortSegs = () => S.p.segments.sort((a, b) => a.start - b.start || a.end - b.end);
const joinWords = (ws) => ws.map((w) => w[2]).join("").trim();

function snapshot() {
  return JSON.stringify({ speakers: S.p.speakers, segments: S.p.segments, summary: S.p.summary });
}
/** Para campos de texto: guarda el estado al enfocar, y solo lo apila si de verdad se edita. */
let pendingSnap = null;
const armHistory = () => (pendingSnap = snapshot());
function commitPending() { if (pendingSnap) { S.history.push(pendingSnap); S.future = []; pendingSnap = null; } }
function pushHistory() {
  S.history.push(snapshot());
  if (S.history.length > 100) S.history.shift();
  S.future = [];
}
function restore(json) {
  const d = JSON.parse(json);
  Object.assign(S.p, d);
  if (!selSeg()) S.sel = null;
  markDirty(); renderAll();
}
function undo() { if (S.history.length) { S.future.push(snapshot()); restore(S.history.pop()); } }
function redo() { if (S.future.length) { S.history.push(snapshot()); restore(S.future.pop()); } }

/** Aplica un cambio con deshacer + guardado automático + repintado. */
function mutate(fn) {
  pushHistory();
  fn();
  sortSegs();
  markDirty();
  renderAll();
}

// ------------------------------------------------------------------ guardado
function setSaveState(t) { $("#save-state").textContent = t; }
function markDirty() {
  S.dirty = true;
  setSaveState("Sin guardar…");
  clearTimeout(S.saveTimer);
  S.saveTimer = setTimeout(save, 1200);
}
async function save() {
  if (!S.p || !S.dirty) return;
  clearTimeout(S.saveTimer);
  S.dirty = false;
  setSaveState("Guardando…");
  const body = { name: S.p.name, speakers: S.p.speakers, segments: S.p.segments, summary: S.p.summary };
  S.saving = api("PUT", `/api/projects/${S.p.id}`, body)
    .then(() => setSaveState(S.dirty ? "Sin guardar…" : "Guardado"))
    .catch((e) => { S.dirty = true; setSaveState("Error al guardar"); toast(e.message); });
  return S.saving;
}
window.addEventListener("beforeunload", () => {
  if (S.p && S.dirty) {
    fetch(`/api/projects/${S.p.id}`, {
      method: "PUT", keepalive: true, headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: S.p.name, speakers: S.p.speakers, segments: S.p.segments, summary: S.p.summary }),
    });
  }
});

// ------------------------------------------------------------------ inicio
async function showHome() {
  if (S.p) await save();
  stopAudio();
  S.p = null;
  $("#home").hidden = false; $("#editor").hidden = true;
  $("#proj-name").hidden = true; $("#btn-process").hidden = true; $("#export-wrap").hidden = true;
  $("#job").hidden = true; setSaveState("");
  await loadList();
}

async function loadList() {
  const list = await api("GET", "/api/projects");
  const box = $("#project-list");
  box.replaceChildren();
  if (!list.length) box.append(h("div", { class: "muted" }, "Aún no hay llamadas. Importa una grabación para empezar."));
  for (const p of list) {
    const badge = p.busy ? h("span", { class: "badge" }, "Procesando…")
      : p.processed ? h("span", { class: "badge ok" }, "Transcrita") : h("span", { class: "badge" }, "Sin procesar");
    box.append(h("div", { class: "card", onclick: () => openProject(p.id) },
      h("div", { class: "name" }, p.name || p.id),
      h("div", { class: "row-b" }, h("span", { class: "muted small" }, `${p.created || ""} · ${fmt(p.duration)}`), badge),
      h("div", { class: "row-b" }, h("span"),
        h("button", { class: "ghost small danger", title: "Borrar llamada",
          onclick: async (e) => {
            e.stopPropagation();
            if (!confirm(`¿Borrar «${p.name}» y su audio? No se puede deshacer.`)) return;
            await api("DELETE", `/api/projects/${p.id}`); loadList();
          } }, "Borrar"))));
  }
  clearTimeout(S.listPoll);
  if (list.some((p) => p.busy) && !S.p) S.listPoll = setTimeout(loadList, 2000);
}

function uploadFile(file) {
  const fd = new FormData();
  fd.append("audio", file);
  fd.append("name", file.name.replace(/\.[^.]+$/, ""));
  const xhr = new XMLHttpRequest();
  const up = $("#upload");
  up.hidden = false;
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) up.textContent = `Importando… ${Math.round((100 * e.loaded) / e.total)}%`; };
  xhr.onload = () => {
    up.hidden = true;
    let data = {};
    try { data = JSON.parse(xhr.responseText); } catch { /* */ }
    if (xhr.status >= 300) return toast(data.error || "No se pudo importar");
    openProject(data.id);
  };
  xhr.onerror = () => { up.hidden = true; toast("Error al importar"); };
  xhr.open("POST", "/api/projects");
  xhr.send(fd);
}
$("#file-input").addEventListener("change", (e) => { if (e.target.files[0]) uploadFile(e.target.files[0]); e.target.value = ""; });
const drop = $("#drop");
["dragenter", "dragover"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); if (!S.p) drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
document.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f && !S.p) uploadFile(f); });

// ------------------------------------------------------------------ abrir proyecto
async function openProject(id) {
  S.p = await api("GET", `/api/projects/${id}`);
  S.peaks = await api("GET", `/api/projects/${id}/peaks`);
  S.sel = null; S.history = []; S.future = []; S.dirty = false;
  $("#home").hidden = true; $("#editor").hidden = false;
  const nm = $("#proj-name"); nm.hidden = false; nm.value = S.p.name || "";
  $("#btn-process").hidden = false; $("#export-wrap").hidden = false;
  setSaveState("");
  audio.src = `/api/projects/${id}/audio`;
  $("#summary").value = S.p.summary || "";
  fitZoom();
  renderAll();
  startPolling();
}

$("#proj-name").addEventListener("input", (e) => { S.p.name = e.target.value; markDirty(); });
$("#btn-home").onclick = showHome;

// ------------------------------------------------------------------ trabajos
function startPolling() {
  clearInterval(S.poll);
  const tick = async () => {
    if (!S.p) return clearInterval(S.poll);
    let jobs;
    try { jobs = await api("GET", `/api/projects/${S.p.id}/jobs`); } catch { return; }
    const active = jobs.find((j) => j.state === "en curso") || jobs.find((j) => j.state === "en cola");
    const box = $("#job");
    if (active) {
      box.hidden = false;
      $("#job-stage").textContent = active.state === "en cola" ? "En cola…" : active.stage || active.kind;
      $("#job-pct").textContent = Math.round(active.progress * 100) + "%";
      $("#job-bar").style.width = active.progress * 100 + "%";
      $("#job-cancel").onclick = () => api("POST", `/api/jobs/${active.id}/cancel`);
    } else box.hidden = true;
    $("#btn-process").disabled = $("#btn-summary").disabled = !!active;
    for (const j of jobs) {
      const prev = S.lastJobs[j.id];
      if (prev && prev !== j.state && ["hecho", "error", "cancelado"].includes(j.state)) await onJobDone(j);
      S.lastJobs[j.id] = j.state;
    }
  };
  tick();
  S.poll = setInterval(tick, 1000);
}

async function onJobDone(j) {
  if (j.state === "error") return toast(`Error (${j.kind}): ${j.error}`);
  if (j.state === "cancelado") return toast("Cancelado");
  const fresh = await api("GET", `/api/projects/${S.p.id}`);
  if (j.kind === "resumen") {
    pushHistory();
    S.p.summary = fresh.summary; $("#summary").value = fresh.summary;
    switchTab("sum"); toast("Resumen generado");
  } else {
    S.p.duration = fresh.duration; S.p.channels = fresh.channels;
    if (j.kind === "procesar") {
      S.p.speakers = fresh.speakers; S.p.segments = fresh.segments; S.p.processed = true;
      S.p.stereo_mode = fresh.stereo_mode; S.history = []; S.future = []; S.sel = null;
      toast("Transcripción lista. Revisa los hablantes y los cortes.");
    }
    S.peaks = await api("GET", `/api/projects/${S.p.id}/peaks`);
    fitZoom();
  }
  renderAll();
}

// ------------------------------------------------------------------ audio
function ensureAudioGraph() {
  if (S.audioCtx) return;
  try {
    const ctx = new AudioContext();
    const src = ctx.createMediaElementSource(audio);
    const split = ctx.createChannelSplitter(2), merge = ctx.createChannelMerger(2);
    const gL = ctx.createGain(), gR = ctx.createGain();
    src.connect(split);
    split.connect(gL, 0); split.connect(gR, 1);
    for (const g of [gL, gR]) { g.connect(merge, 0, 0); g.connect(merge, 0, 1); }
    merge.connect(ctx.destination);
    S.audioCtx = ctx; S.gains = { gL, gR };
    applyChannel();
  } catch (e) { console.warn("Sin Web Audio:", e); }
}
function applyChannel() {
  $$("#chan-ctl button").forEach((b) => b.classList.toggle("on", b.dataset.chan === S.chan));
  if (!S.gains) return;
  const mono = (S.p && S.p.channels || 1) < 2;
  const L = S.chan === "R" && !mono ? 0 : 1, R = S.chan === "L" || mono ? 0 : 1;
  const k = L && R ? 0.6 : 1;
  S.gains.gL.gain.value = L * (mono ? 1 : k);
  S.gains.gR.gain.value = R * k;
}
$$("#chan-ctl button").forEach((b) => (b.onclick = () => { S.chan = b.dataset.chan; ensureAudioGraph(); applyChannel(); }));
$("#rate").onchange = (e) => (audio.playbackRate = +e.target.value);

function play(from, to) {
  ensureAudioGraph();
  if (S.audioCtx && S.audioCtx.state === "suspended") S.audioCtx.resume();
  if (from != null) audio.currentTime = from;
  S.stopAt = to ?? null;
  audio.play().catch((e) => toast("No se pudo reproducir: " + e.message));
}
function togglePlay() { audio.paused ? play() : audio.pause(); }
function stopAudio() { audio.pause(); S.stopAt = null; }
function seek(t) { audio.currentTime = Math.max(0, Math.min(t, S.p.duration || t)); S.stopAt = null; updatePlayhead(); }
$("#btn-play").onclick = togglePlay;
audio.addEventListener("play", () => { $("#btn-play").textContent = "❚❚"; loop(); });
audio.addEventListener("pause", () => { $("#btn-play").textContent = "▶"; updatePlayhead(); });
audio.addEventListener("loadedmetadata", () => {
  if (S.p && !S.p.duration && isFinite(audio.duration)) { S.p.duration = audio.duration; fitZoom(); renderAll(); }
});
function loop() {
  cancelAnimationFrame(S.raf);
  const step = () => {
    if (S.stopAt != null && audio.currentTime >= S.stopAt) { audio.pause(); S.stopAt = null; }
    updatePlayhead(true);
    if (!audio.paused) S.raf = requestAnimationFrame(step);
  };
  step();
}

function updatePlayhead(follow = false) {
  if (!S.p) return;
  const t = audio.currentTime || 0;
  $("#playhead").style.left = t * S.pps + "px";
  $("#clock").textContent = `${fmt(t, true)} / ${fmt(S.p.duration)}`;
  if (follow && !audio.paused) {
    const x = t * S.pps, w = viewport.clientWidth;
    if (x < viewport.scrollLeft || x > viewport.scrollLeft + w - 20) viewport.scrollLeft = x - w * 0.1;
  }
  if (Math.abs(t - S.lastNow) > 0.15) { S.lastNow = t; highlightNow(t); }
}

function highlightNow(t) {
  const rows = $$("#transcript .tr.now");
  rows.forEach((r) => r.classList.remove("now"));
  let first = null;
  for (const s of segs()) {
    if (s.start > t) break;
    if (s.end >= t) {
      const r = document.getElementById("tr-" + s.id);
      if (r) { r.classList.add("now"); first = first || r; }
    }
  }
  if (first && $("#follow").checked && !audio.paused && !S.editingText) {
    const box = $("#transcript"), rb = first.getBoundingClientRect(), bb = box.getBoundingClientRect();
    if (rb.top < bb.top || rb.bottom > bb.bottom) box.scrollTop += rb.top - bb.top - bb.height / 3;
  }
}

// ------------------------------------------------------------------ zoom
function fitPps() { return Math.max(0.5, (viewport.clientWidth - 10) / Math.max(1, S.p.duration || 1)); }
function setPps(pps, anchorT, anchorX) {
  const min = fitPps();
  S.pps = Math.max(min, Math.min(MAX_PPS, pps));
  const v = Math.log(S.pps / min) / Math.log(MAX_PPS / min);
  $("#zoom").value = isFinite(v) ? Math.round(v * 1000) : 0;
  layout();
  if (anchorT != null) viewport.scrollLeft = anchorT * S.pps - anchorX;
  drawCanvases();
}
function fitZoom() { setPps(fitPps()); viewport.scrollLeft = 0; }
$("#zoom").oninput = (e) => {
  const min = fitPps(), center = (viewport.scrollLeft + viewport.clientWidth / 2) / S.pps;
  setPps(min * Math.pow(MAX_PPS / min, e.target.value / 1000), center, viewport.clientWidth / 2);
};
$("#btn-fit").onclick = fitZoom;
viewport.addEventListener("wheel", (e) => {
  if (!e.ctrlKey) return;
  e.preventDefault();
  const x = e.clientX - viewport.getBoundingClientRect().left;
  const t = (viewport.scrollLeft + x) / S.pps;
  setPps(S.pps * (e.deltaY < 0 ? 1.25 : 0.8), t, x);
}, { passive: false });
viewport.addEventListener("scroll", drawCanvases);
window.addEventListener("resize", () => { if (S.p) { setPps(Math.max(S.pps, fitPps())); } });

// ------------------------------------------------------------------ pistas
function laneList() {
  const lanes = [];
  const nch = (S.peaks && S.peaks.channels.length) || 0;
  if (nch >= 2) {
    lanes.push({ kind: "wave", ch: 0, name: "Onda · canal izq. (Yo)" });
    lanes.push({ kind: "wave", ch: 1, name: "Onda · canal der. (Remoto)" });
  } else if (nch === 1) lanes.push({ kind: "wave", ch: 0, name: "Onda" });
  for (const s of S.p.speakers) lanes.push({ kind: "spk", id: s.id });
  lanes.push({ kind: "add" });
  return lanes;
}

function layout() {
  inner.style.width = Math.max(viewport.clientWidth, Math.ceil((S.p.duration || 0) * S.pps) + 40) + "px";
  const byId = new Map(segs().map((s) => [s.id, s]));
  for (const el of $$(".seg", inner)) {
    const s = byId.get(el.dataset.id);
    if (s) positionSeg(el, s);
  }
  updatePlayhead();
}
function positionSeg(el, s) {
  el.style.left = s.start * S.pps + "px";
  el.style.width = Math.max(3, (s.end - s.start) * S.pps) + "px";
}

function renderAll() {
  if (!S.p) return;
  renderTimeline();
  renderTranscript();
  renderInspector();
  $("#btn-process").textContent = S.p.processed ? "Volver a procesar" : "Transcribir y diarizar";
  $("#btn-undo").disabled = !S.history.length;
  $("#btn-redo").disabled = !S.future.length;
}

function renderTimeline() {
  const heads = $("#tl-heads"), lanesEl = $("#lanes");
  heads.replaceChildren(h("div", { class: "head ruler" }, "Tiempo"));
  lanesEl.replaceChildren();
  const counts = {};
  for (const s of segs()) counts[s.speaker] = (counts[s.speaker] || 0) + 1;

  laneList().forEach((ln) => {
    if (ln.kind === "wave") {
      heads.append(h("div", { class: "head wave", style: `height:${WAVE_H}px` }, ln.name));
      const lane = h("div", { class: "lane wave", style: `height:${WAVE_H}px`, dataset: { ch: ln.ch } },
        h("canvas", { class: "cv wavecv", height: WAVE_H }));
      lane.addEventListener("mousedown", (e) => seekFromEvent(e));
      lanesEl.append(lane);
    } else if (ln.kind === "spk") {
      const sp = spk(ln.id), idx = S.p.speakers.indexOf(sp);
      const others = S.p.speakers.filter((o) => o.id !== sp.id);
      const merge = h("select", { title: "Fusionar este hablante en otro", class: "merge",
        onchange: (e) => { if (e.target.value) mergeSpeaker(sp.id, e.target.value); e.target.value = ""; } },
        h("option", { value: "" }, "⇢"), others.map((o) => h("option", { value: o.id }, "Fusionar en " + o.label)));
      heads.append(h("div", { class: "head", style: `height:${LANE_H}px` },
        h("span", { class: "key", title: `Tecla ${idx + 1}` }, idx < 9 ? String(idx + 1) : ""),
        h("input", { type: "color", class: "swatch", value: sp.color, title: "Color",
          onchange: (e) => mutate(() => (sp.color = e.target.value)) }),
        h("input", { class: "label", value: sp.label, title: "Nombre (clic para editar)",
          onchange: (e) => renameSpeaker(sp.id, e.target.value) }),
        h("span", { class: "count", title: "Segmentos" }, String(counts[sp.id] || 0)),
        h("button", { class: "ghost", title: "Escuchar una muestra", onclick: () => sampleSpeaker(sp.id) }, "▶"),
        counts[sp.id] ? (others.length ? merge : null)
          : h("button", { class: "ghost", title: "Quitar pista vacía", onclick: () => mutate(() => S.p.speakers.splice(S.p.speakers.indexOf(sp), 1)) }, "✕")));
      const lane = h("div", { class: "lane spk", style: `height:${LANE_H}px`, dataset: { spk: sp.id } });
      lane.addEventListener("mousedown", (e) => { if (e.target === lane) { S.sel = null; seekFromEvent(e); renderSelection(); } });
      for (const s of segs()) if (s.speaker === sp.id) lane.append(segEl(s));
      lanesEl.append(lane);
    } else {
      heads.append(h("div", { class: "head add", style: `height:${ADD_H}px` },
        h("button", { class: "ghost small", onclick: addSpeaker }, "+ Añadir hablante"),
        !S.p.processed ? h("span", { class: "muted small" }, "Sin transcribir") : null));
      lanesEl.append(h("div", { class: "lane", style: `height:${ADD_H}px` }));
    }
  });
  layout();
  drawCanvases();
}

function segEl(s) {
  const el = h("div", { class: "seg" + (s.id === S.sel ? " sel" : "") + (s.flag ? " flag" : ""),
    dataset: { id: s.id }, title: `${fmt(s.start, true)}–${fmt(s.end, true)}  ${label(s.speaker)}${s.flag ? " (" + s.flag + ")" : ""}\n${s.text}` },
  s.text);
  el.style.background = color(s.speaker);
  positionSeg(el, s);
  el.addEventListener("mousedown", (e) => startDrag(e, s, el));
  el.addEventListener("dblclick", () => play(s.start, s.end));
  return el;
}

function timeFromEvent(e) { return (e.clientX - inner.getBoundingClientRect().left) / S.pps; }
function seekFromEvent(e) { if (e.button === 0) seek(timeFromEvent(e)); }
$("#cv-ruler").addEventListener("mousedown", seekFromEvent);

// ------------------------------------------------------------------ dibujo
function drawCanvases() {
  if (!S.p) return;
  const w = viewport.clientWidth, x0 = viewport.scrollLeft, dpr = window.devicePixelRatio || 1;
  const css = getComputedStyle(document.documentElement);
  const waveColor = css.getPropertyValue("--wave").trim(), muted = css.getPropertyValue("--muted").trim(),
    border = css.getPropertyValue("--border").trim();
  const prep = (cv, height) => {
    cv.style.left = x0 + "px"; cv.style.width = w + "px"; cv.style.height = height + "px";
    cv.width = Math.round(w * dpr); cv.height = Math.round(height * dpr);
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, height);
    return g;
  };
  // Regla
  const g = prep($("#cv-ruler"), RULER_H);
  const steps = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800];
  const step = steps.find((s) => s * S.pps >= 70) || 3600;
  g.fillStyle = muted; g.strokeStyle = border; g.font = "11px system-ui, sans-serif";
  for (let t = Math.floor(x0 / S.pps / step) * step; t * S.pps < x0 + w; t += step) {
    const x = Math.round(t * S.pps - x0) + 0.5;
    g.beginPath(); g.moveTo(x, RULER_H - 7); g.lineTo(x, RULER_H); g.stroke();
    g.fillText(fmt(t, step < 1), x + 3, 13);
  }
  // Ondas
  for (const cv of $$(".wavecv")) {
    const ch = +cv.parentElement.dataset.ch;
    const gg = prep(cv, WAVE_H);
    const data = S.peaks && S.peaks.channels[ch];
    if (!data) continue;
    const pps = S.peaks.pps, mid = WAVE_H / 2;
    gg.fillStyle = waveColor;
    for (let px = 0; px < w; px++) {
      const a = Math.floor(((x0 + px) / S.pps) * pps), b = Math.max(a + 1, Math.floor(((x0 + px + 1) / S.pps) * pps));
      if (a >= data.length) break;
      let m = 0;
      for (let i = a; i < b && i < data.length; i++) if (data[i] > m) m = data[i];
      const hgt = Math.max(1, (m / 100) * (WAVE_H - 6));
      gg.fillRect(px, mid - hgt / 2, 1, hgt);
    }
  }
}

// ------------------------------------------------------------------ arrastrar
function startDrag(e, s, el) {
  if (e.button !== 0) return;
  e.preventDefault(); e.stopPropagation();
  const rect = el.getBoundingClientRect(), off = e.clientX - rect.left;
  const mode = rect.width >= 16 && off < 6 ? "l" : rect.width >= 16 && off > rect.width - 6 ? "r" : "move";
  const t0 = timeFromEvent(e), orig = { start: s.start, end: s.end, speaker: s.speaker };
  const before = snapshot();
  let moved = false, target = null;
  select(s.id, false);

  const onMove = (ev) => {
    const dt = timeFromEvent(ev) - t0;
    if (!moved && Math.abs(ev.clientX - e.clientX) < 3 && Math.abs(ev.clientY - e.clientY) < 3) return;
    moved = true;
    if (mode === "l") s.start = r3(Math.max(0, Math.min(orig.start + dt, s.end - 0.1)));
    else if (mode === "r") s.end = r3(Math.min(S.p.duration || Infinity, Math.max(orig.end + dt, s.start + 0.1)));
    else {
      el.classList.add("dragging");
      target = null;
      for (const ln of $$(".lane.spk")) {
        const r = ln.getBoundingClientRect();
        const hit = ev.clientY >= r.top && ev.clientY < r.bottom;
        ln.classList.toggle("drop-target", hit && ln.dataset.spk !== orig.speaker);
        if (hit) target = ln.dataset.spk;
      }
    }
    if (mode !== "move") { positionSeg(el, s); renderInspector(); }
  };
  const onUp = () => {
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
    el.classList.remove("dragging");
    $$(".lane.drop-target").forEach((l) => l.classList.remove("drop-target"));
    if (!moved) { seek(s.start); return; }
    if (mode === "move" && target && target !== orig.speaker) s.speaker = target;
    if (s.start !== orig.start || s.end !== orig.end || s.speaker !== orig.speaker) {
      S.history.push(before); S.future = [];
      sortSegs(); markDirty(); renderAll();
    }
  };
  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);
}

// ------------------------------------------------------------------ selección / inspector
function select(id, scroll = true) {
  S.sel = id;
  renderSelection();
  const s = selSeg();
  if (s && scroll) {
    const x = s.start * S.pps;
    if (x < viewport.scrollLeft || x > viewport.scrollLeft + viewport.clientWidth - 40) viewport.scrollLeft = x - 80;
    const row = document.getElementById("tr-" + id);
    if (row) row.scrollIntoView({ block: "nearest" });
  }
}
function renderSelection() {
  $$(".seg.sel").forEach((e) => e.classList.remove("sel"));
  $$(".tr.sel").forEach((e) => e.classList.remove("sel"));
  if (S.sel) {
    const el = $(`.seg[data-id="${S.sel}"]`); if (el) el.classList.add("sel");
    const row = document.getElementById("tr-" + S.sel); if (row) row.classList.add("sel");
  }
  renderInspector();
  switchTab("seg", false);
}

function renderInspector() {
  const s = S.p && selSeg();
  $("#inspector").hidden = !s; $("#inspector-empty").hidden = !!s;
  if (!s) return;
  const sel = $("#ins-speaker");
  sel.replaceChildren(...S.p.speakers.map((sp) => h("option", { value: sp.id, selected: sp.id === s.speaker }, sp.label)));
  if (document.activeElement !== $("#ins-start")) $("#ins-start").value = s.start.toFixed(2);
  if (document.activeElement !== $("#ins-end")) $("#ins-end").value = s.end.toFixed(2);
  if (document.activeElement !== $("#ins-text")) $("#ins-text").value = s.text;
  $("#ins-meta").textContent = `Duración ${(s.end - s.start).toFixed(1)} s` + (s.lang ? ` · idioma ${s.lang}` : "") + (s.flag ? ` · ⚠ ${s.flag}` : "");
}
$("#ins-speaker").onchange = (e) => mutate(() => (selSeg().speaker = e.target.value));
$("#ins-start").onchange = (e) => mutate(() => { const s = selSeg(); s.start = r3(Math.max(0, Math.min(+e.target.value, s.end - 0.1))); });
$("#ins-end").onchange = (e) => mutate(() => { const s = selSeg(); s.end = r3(Math.max(+e.target.value, s.start + 0.1)); });
$("#ins-text").addEventListener("focus", armHistory);
$("#ins-text").addEventListener("input", (e) => {
  commitPending();
  const s = selSeg(); s.text = e.target.value; markDirty();
  const row = document.getElementById("tr-" + s.id); if (row) $(".txt", row).textContent = s.text;
  const blk = $(`.seg[data-id="${s.id}"]`); if (blk) blk.textContent = s.text;
});
$("#ins-play").onclick = () => { const s = selSeg(); if (s) play(s.start, s.end); };
$("#ins-split").onclick = splitAtCursor;
$("#ins-merge").onclick = mergeWithNext;
$("#ins-delete").onclick = deleteSelected;

// ------------------------------------------------------------------ operaciones
function splitAtCursor() {
  const s = selSeg();
  if (!s) return;
  const t = audio.currentTime;
  if (!(t > s.start + 0.05 && t < s.end - 0.05)) return toast("Coloca el cursor dentro del segmento seleccionado (clic en la regla o reproduce hasta el punto).");
  mutate(() => {
    const words = s.words || [];
    let a, b, wa = [], wb = [];
    if (words.length) {
      wa = words.filter((w) => (w[0] + w[1]) / 2 < t); wb = words.filter((w) => (w[0] + w[1]) / 2 >= t);
      a = joinWords(wa); b = joinWords(wb);
    } else {
      const frac = (t - s.start) / (s.end - s.start);
      let cut = Math.round(s.text.length * frac);
      const sp = s.text.indexOf(" ", cut); cut = sp === -1 ? s.text.length : sp;
      a = s.text.slice(0, cut).trim(); b = s.text.slice(cut).trim();
    }
    const n = { ...s, id: uid(), start: r3(t), text: b, words: wb };
    Object.assign(s, { end: r3(t), text: a, words: wa });
    S.p.segments.push(n);
  });
}

function mergeWithNext() {
  const s = selSeg();
  if (!s) return;
  const list = segs(), i = list.indexOf(s), n = list[i + 1];
  if (!n) return toast("No hay un segmento siguiente.");
  mutate(() => {
    s.start = Math.min(s.start, n.start); s.end = Math.max(s.end, n.end);
    s.text = [s.text, n.text].filter(Boolean).join(" ");
    s.words = [...(s.words || []), ...(n.words || [])].sort((a, b) => a[0] - b[0]);
    delete s.flag;
    S.p.segments.splice(S.p.segments.indexOf(n), 1);
  });
}

function deleteSelected() {
  const s = selSeg();
  if (!s) return;
  const list = segs(), i = list.indexOf(s), next = list[i + 1] || list[i - 1];
  mutate(() => { S.p.segments.splice(S.p.segments.indexOf(s), 1); S.sel = next ? next.id : null; });
}

function assignSelected(n) {
  const s = selSeg(), sp = S.p.speakers[n];
  if (s && sp && s.speaker !== sp.id) mutate(() => (s.speaker = sp.id));
}

function renameSpeaker(id, newLabel) {
  newLabel = newLabel.trim();
  const sp = spk(id);
  if (!newLabel || newLabel === sp.label) return renderAll();
  mutate(() => {
    const old = sp.label;
    sp.label = newLabel;
    if (S.p.summary) {
      S.p.summary = S.p.summary.replace(new RegExp(`(?<![\\p{L}\\p{N}])${escRe(old)}(?![\\p{L}\\p{N}])`, "gu"), newLabel);
      $("#summary").value = S.p.summary;
    }
  });
}

function mergeSpeaker(from, into) {
  if (!confirm(`¿Pasar todos los segmentos de «${label(from)}» a «${label(into)}»?`)) return;
  mutate(() => {
    for (const s of S.p.segments) if (s.speaker === from) s.speaker = into;
    S.p.speakers = S.p.speakers.filter((s) => s.id !== from);
  });
}

function addSpeaker() {
  const nums = S.p.speakers.map((s) => +(/^N(\d+)$/.exec(s.id) || [0, 0])[1]);
  const id = "N" + (Math.max(0, ...nums) + 1);
  const palette = ["#2f7ed8", "#e4572e", "#29a36a", "#a05cd6", "#d99a00", "#1aa3a3", "#d6457a", "#6b8e23", "#8c6d46", "#5a6acf"];
  mutate(() => S.p.speakers.push({ id, label: id, color: palette[S.p.speakers.length % palette.length] }));
}

function sampleSpeaker(id) {
  const list = segs().filter((s) => s.speaker === id);
  if (!list.length) return toast("Este hablante no tiene segmentos.");
  const best = list.reduce((a, b) => (b.end - b.start > a.end - a.start ? b : a));
  select(best.id);
  play(best.start, Math.min(best.end, best.start + 8));
}

// ------------------------------------------------------------------ transcripción
function renderTranscript() {
  const box = $("#transcript");
  const top = box.scrollTop;
  box.replaceChildren();
  if (!segs().length) {
    box.append(h("div", { class: "muted", style: "padding:14px" },
      S.p.processed ? "No se detectó voz." : "Pulsa «Transcribir y diarizar» para empezar."));
    return;
  }
  const frag = document.createDocumentFragment();
  for (const s of segs()) {
    const txt = h("div", { class: "txt", contentEditable: "true", spellcheck: false }, s.text);
    txt.addEventListener("focus", () => { armHistory(); S.editingText = true; if (S.sel !== s.id) select(s.id, false); });
    txt.addEventListener("blur", () => { S.editingText = false; $("#btn-undo").disabled = !S.history.length; });
    txt.addEventListener("input", () => {
      commitPending();
      s.text = txt.textContent; markDirty();
      const blk = $(`.seg[data-id="${s.id}"]`); if (blk) blk.textContent = s.text;
      if (document.activeElement !== $("#ins-text")) $("#ins-text").value = s.text;
    });
    txt.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); txt.blur(); } if (e.key === "Escape") txt.blur(); });
    const who = h("div", { class: "who", title: "Clic: reproducir este segmento" }, label(s.speaker));
    who.style.color = color(s.speaker);
    who.onclick = () => { select(s.id); play(s.start, s.end); };
    frag.append(h("div", { class: "tr" + (s.id === S.sel ? " sel" : "") + (s.flag ? " flag" : ""), id: "tr-" + s.id,
      title: s.flag ? "⚠ " + s.flag : "" },
    h("div", { class: "t mono", title: "Ir a este punto", onclick: () => { select(s.id); seek(s.start); } }, fmt(s.start)),
    who, txt));
  }
  box.append(frag);
  box.scrollTop = top;
  applySearch();
}
function applySearch() {
  const q = norm($("#search").value.trim());
  for (const s of segs()) {
    const row = document.getElementById("tr-" + s.id);
    if (row) row.classList.toggle("hide", !!q && !norm(s.text).includes(q) && !norm(label(s.speaker)).includes(q));
  }
}
$("#search").addEventListener("input", applySearch);

// ------------------------------------------------------------------ pestañas / resumen
function switchTab(tab, force = true) {
  if (!force && tab === "seg" && !S.sel) return;
  $$(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  $("#tab-seg").hidden = tab !== "seg"; $("#tab-sum").hidden = tab !== "sum";
  if (tab === "sum") updateSummaryHint();
}
$$(".tabs button").forEach((b) => (b.onclick = () => switchTab(b.dataset.tab)));
$("#summary").addEventListener("focus", armHistory);
$("#summary").addEventListener("input", (e) => { commitPending(); S.p.summary = e.target.value; markDirty(); });
$("#btn-copy-summary").onclick = () => copyText($("#summary").value);
async function updateSummaryHint() {
  const s = await api("GET", "/api/settings");
  $("#sum-hint").textContent = s.gguf_path
    ? `Modelo: ${s.gguf_path.split(/[\\/]/).pop()} · Revisa antes los nombres de los hablantes: el resumen los usa.`
    : "Configura un modelo .gguf en Ajustes para generar resúmenes.";
}
$("#btn-summary").onclick = async () => {
  if (!segs().length) return toast("Primero transcribe la llamada.");
  if (S.p.summary && !confirm("¿Reemplazar el resumen actual?")) return;
  await save(); if (S.saving) await S.saving;
  try { await api("POST", `/api/projects/${S.p.id}/summary`); startPolling(); } catch (e) { toast(e.message); }
};

// ------------------------------------------------------------------ procesar
$("#btn-process").onclick = () => {
  const d = $("#dlg-process");
  const sel = $("#proc-num");
  if (sel.options.length === 1) for (let i = 1; i <= 10; i++) sel.append(h("option", { value: i }, String(i)));
  const stereo = (S.p.channels || 0) >= 2;
  $("#proc-info").textContent = stereo
    ? "Grabación estéreo: el canal izquierdo será «Yo» y el derecho se separará en N1, N2…"
    : "Grabación mono: se separará todo en N1, N2…";
  $("#proc-mix-wrap").hidden = !stereo;
  $("#proc-warn").hidden = !segs().length;
  d.returnValue = "";
  d.showModal();
  d.onclose = async () => {
    if (d.returnValue !== "ok") return;
    await save();
    try {
      await api("POST", `/api/projects/${S.p.id}/process`, { num_speakers: +sel.value, mix_channels: $("#proc-mix").checked });
      startPolling();
    } catch (e) { toast(e.message); }
  };
};

// ------------------------------------------------------------------ exportar
$("#btn-export").onclick = (e) => { e.stopPropagation(); $("#export-menu").hidden = !$("#export-menu").hidden; };
document.addEventListener("click", () => ($("#export-menu").hidden = true));
$("#export-menu").addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  await save(); if (S.saving) await S.saving;
  try {
    if (b.dataset.export) {
      const r = await api("POST", `/api/projects/${S.p.id}/export/${b.dataset.export}`);
      toast("Guardado: " + r.path, { label: "Abrir carpeta", fn: () => api("POST", `/api/projects/${S.p.id}/open`, { sub: "exportado" }) });
    } else if (b.dataset.copy === "summary") copyText(S.p.summary || "");
    else if (b.dataset.copy === "transcript") copyText((await api("POST", `/api/projects/${S.p.id}/export/txt`)).text);
    else if (b.dataset.copy === "claude") copyText((await api("POST", `/api/projects/${S.p.id}/export/claude`)).text);
    else if (b.dataset.open) api("POST", `/api/projects/${S.p.id}/open`, {});
  } catch (err) { toast(err.message); }
});

// ------------------------------------------------------------------ ajustes
$("#btn-settings").onclick = async () => {
  const s = await api("GET", "/api/settings");
  const f = $("#settings-form");
  for (const el of f.elements) {
    if (!el.name || !(el.name in s)) continue;
    if (el.type === "checkbox") el.checked = !!s[el.name]; else el.value = s[el.name];
  }
  $("#cur-projects").textContent = "Actual: " + s._projects_dir;
  $("#cur-models").textContent = "Actual: " + s._models_dir;
  $("#pick-gguf").hidden = !s._has_picker;
  const d = $("#dlg-settings");
  d.returnValue = "";
  d.showModal();
  d.onclose = async () => {
    if (d.returnValue !== "ok") return;
    const body = {};
    for (const el of f.elements) if (el.name) body[el.name] = el.type === "checkbox" ? el.checked : el.value;
    try { await api("PUT", "/api/settings", body); toast("Ajustes guardados"); updateSummaryHint(); } catch (e) { toast(e.message); }
  };
};
$("#pick-gguf").onclick = async () => {
  try { const r = await api("POST", "/api/pick", { kind: "gguf" }); if (r.path) $("#settings-form").elements.gguf_path.value = r.path; }
  catch (e) { toast(e.message); }
};
$("#btn-help").onclick = () => $("#dlg-help").showModal();
$("#btn-undo").onclick = undo;
$("#btn-redo").onclick = redo;

// ------------------------------------------------------------------ teclado
document.addEventListener("keydown", (e) => {
  if (!S.p || $("#editor").hidden || document.querySelector("dialog[open]")) return;
  const tag = e.target.tagName;
  const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.target.isContentEditable;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !typing) {
    e.preventDefault(); return e.shiftKey ? redo() : undo();
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y" && !typing) { e.preventDefault(); return redo(); }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); return save(); }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  const list = segs(), cur = selSeg(), i = cur ? list.indexOf(cur) : -1;
  switch (e.key) {
    case " ": e.preventDefault(); togglePlay(); break;
    case "ArrowLeft": e.preventDefault(); seek(audio.currentTime - 5); break;
    case "ArrowRight": e.preventDefault(); seek(audio.currentTime + 5); break;
    case "ArrowUp": e.preventDefault(); if (list.length) { const s = list[Math.max(0, i - 1)]; select(s.id); seek(s.start); } break;
    case "ArrowDown": e.preventDefault(); if (list.length) { const s = list[Math.min(list.length - 1, i + 1)]; select(s.id); seek(s.start); } break;
    case "s": case "S": splitAtCursor(); break;
    case "m": case "M": mergeWithNext(); break;
    case "Delete": case "Backspace": deleteSelected(); break;
    case "Escape": S.sel = null; renderSelection(); break;
    default:
      if (/^[1-9]$/.test(e.key)) assignSelected(+e.key - 1);
  }
});

// ------------------------------------------------------------------ puente con el móvil
const BR = { st: null, lastRec: undefined };
const fmtSecs = (s) => fmt(s);

async function pollBridge() {
  try { BR.st = await api("GET", "/api/bridge"); } catch { BR.st = null; }
  renderBridge();
  setTimeout(pollBridge, $("#dlg-bridge").open ? 400 : 1000);
}

function bridgeSteps(st) {
  const steps = [];
  const phoneDev = (st.devices || []).find((d) => d.state === "device");
  steps.push(st.adb ? ["ok", "adb encontrado"] : ["bad", "Falta adb: descarga «Android SDK Platform-Tools», descomprímelo en C:\\platform-tools (o indica la ruta en Configuración)."]);
  if (st.adb) {
    steps.push(phoneDev && st.reverse ? ["ok", `Móvil por USB: ${phoneDev.model || phoneDev.serial}`]
      : ["bad", st.adb_error || "Conecta el móvil por USB con la depuración USB activada."]);
  }
  steps.push(st.phone ? ["ok", `App conectada (${st.phone.model})`]
    : ["wait", "Abre CallBridge en el móvil y pulsa «Conectar»."]);
  if (st.phone) steps.push(st.audio ? ["ok", `Audio activo · retardo ${st.buffer_ms} ms` + (st.phone_state.route ? ` · en el móvil: ${st.phone_state.route}` : "")]
    : ["bad", "Audio del PC: " + (st.audio_error || "sin iniciar")]);
  return steps;
}

function renderBridge() {
  const st = BR.st, pill = $("#btn-bridge");
  pill.classList.remove("ok", "warn", "rec");
  if (!st || !st.running) { $("#bridge-label").textContent = "Móvil: apagado"; }
  else if (st.recording) { pill.classList.add("rec"); $("#bridge-label").textContent = "Grabando " + fmtSecs(st.rec_seconds); }
  else if (st.phone && st.audio) { pill.classList.add("ok"); $("#bridge-label").textContent = "Móvil conectado"; }
  else { pill.classList.add("warn"); $("#bridge-label").textContent = st.phone ? "Móvil: sin audio" : "Móvil: esperando"; }

  if (st && BR.lastRec !== st.last_recording) {
    if (BR.lastRec !== undefined && st.last_recording) {
      toast("Grabación guardada como nueva llamada.", { label: "Ver", fn: showHome });
      if (!S.p) loadList();
    }
    BR.lastRec = st.last_recording;
  }
  if (!$("#dlg-bridge").open || !st) return;
  $("#bridge-steps").replaceChildren(...bridgeSteps(st).map(([cls, txt]) =>
    h("li", { class: cls }, h("span", { class: "ic" }, cls === "ok" ? "✔" : cls === "bad" ? "✖" : "…"), h("span", {}, txt))));
  $("#lvl-mic").style.width = Math.min(100, st.mic_level * 140) + "%";
  $("#lvl-remote").style.width = Math.min(100, st.remote_level * 140) + "%";
  const rb = $("#br-record");
  rb.classList.toggle("rec", st.recording);
  rb.textContent = st.recording ? `■ Detener grabación (${fmtSecs(st.rec_seconds)})` : "● Grabar llamada";
  rb.disabled = !st.recording && !(st.phone && st.audio);
  $("#br-toggle").textContent = st.running ? "Detener puente" : "Iniciar puente";
  $("#br-install").hidden = !st.apk;
  $("#br-install").disabled = !(st.devices || []).some((d) => d.state === "device");
}

$("#btn-bridge").onclick = async () => {
  const s = await api("GET", "/api/settings");
  $("#br-adb").value = s.adb_path || "";
  $("#br-autostart").checked = !!s.bridge_autostart;
  $("#br-autorec").checked = !!s.bridge_auto_record;
  $("#br-autoproc").checked = !!s.bridge_auto_process;
  $("#br-auto").textContent = s.bridge_auto_process ? " y se transcribe sola" : "";
  $("#br-adb-pick").hidden = !s._has_picker;
  const devs = await api("GET", "/api/bridge/devices");
  const fill = (sel, list, cur) => {
    const names = [...new Set(list.map((d) => d.name))];
    if (cur && !names.includes(cur)) names.unshift(cur);
    sel.replaceChildren(...names.map((n) => h("option", { value: n, selected: n === cur }, n)));
  };
  fill($("#br-out"), devs.outputs, s.bridge_to_teams);
  fill($("#br-in"), devs.inputs, s.bridge_from_teams);
  if (devs.error) $("#br-config").open = true;
  $("#dlg-bridge").showModal();
  renderBridge();
};
$("#br-record").onclick = async () => {
  try { BR.st = await api("POST", "/api/bridge/record", { on: !(BR.st && BR.st.recording) }); renderBridge(); }
  catch (e) { toast(e.message); }
};
$("#br-toggle").onclick = async () => {
  try { BR.st = await api("POST", BR.st && BR.st.running ? "/api/bridge/stop" : "/api/bridge/start"); renderBridge(); }
  catch (e) { toast(e.message); }
};
$("#br-install").onclick = async () => {
  const b = $("#br-install"); b.disabled = true; b.textContent = "Instalando…";
  try { await api("POST", "/api/bridge/install"); toast("App instalada y abierta en el móvil."); }
  catch (e) { toast(e.message); }
  b.textContent = "Instalar/actualizar app del móvil"; b.disabled = false;
};
$("#br-adb-pick").onclick = async () => {
  try { const r = await api("POST", "/api/pick", { kind: "adb" }); if (r.path) $("#br-adb").value = r.path; } catch (e) { toast(e.message); }
};
$("#br-save").onclick = async () => {
  try {
    await api("PUT", "/api/settings", {
      bridge_to_teams: $("#br-out").value, bridge_from_teams: $("#br-in").value, adb_path: $("#br-adb").value.trim(),
      bridge_autostart: $("#br-autostart").checked, bridge_auto_record: $("#br-autorec").checked,
      bridge_auto_process: $("#br-autoproc").checked,
    });
    if (BR.st && BR.st.running) { await api("POST", "/api/bridge/stop"); await api("POST", "/api/bridge/start"); }
    toast("Configuración del puente guardada");
  } catch (e) { toast(e.message); }
};

pollBridge();
showHome();

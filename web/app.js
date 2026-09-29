import * as pdfjsLib from "./vendor/pdf.min.mjs";
import { snapToHeads } from "./snap.js";

pdfjsLib.GlobalWorkerOptions.workerSrc = "./vendor/pdf.worker.min.mjs";

// Pages are sent to Audiveris at about 300 dpi, which is what it expects.
const OMR_DPI = 300;
const OMR_MAX_SIDE = 4200;

const $ = (id) => document.getElementById(id);
const stage = $("stage");
const canvas = $("page-canvas");
const overlay = $("overlay");
const statusEl = $("status");

const state = {
  pdf: null,
  docId: null,
  name: "",
  page: 1,
  results: new Map(), // page -> {notes, space} or {error}
  busyPage: null,
  generation: 0,
  renderTask: null,
  audiveris: true,
};

// ---------- settings ----------

const settings = { show: true, accidentals: "written", octave: false, colors: true, size: 1, fit: "height" };
try { Object.assign(settings, JSON.parse(localStorage.getItem("sheetcheat.settings") || "{}")); } catch {}

function saveSettings() {
  try { localStorage.setItem("sheetcheat.settings", JSON.stringify(settings)); } catch {}
}

function bindSetting(id, key, prop = "value", parse = (v) => v) {
  const el = $(id);
  el[prop] = settings[key];
  el.addEventListener("input", () => {
    settings[key] = parse(el[prop]);
    saveSettings();
    if (key === "fit") renderPage(); else drawOverlay();
  });
}
bindSetting("opt-show", "show", "checked");
bindSetting("opt-accidentals", "accidentals");
bindSetting("opt-octave", "octave", "checked");
bindSetting("opt-colors", "colors", "checked");
bindSetting("opt-size", "size", "value", Number);
bindSetting("opt-fit", "fit");

// ---------- note names ----------

const PITCH_CLASS = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
const SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];

function labelFor(note) {
  let name = note.name;
  let octave = note.octave;
  if (settings.accidentals !== "written" && note.alter !== 0) {
    const midi = 12 * (note.octave + 1) + PITCH_CLASS[note.step] + note.alter;
    const table = settings.accidentals === "sharps" ? SHARP_NAMES : FLAT_NAMES;
    name = table[((midi % 12) + 12) % 12];
    octave = Math.floor(midi / 12) - 1;
  }
  name = name.replace(/#/g, "♯").replace(/b/g, "♭");
  return { name, octave };
}

// ---------- status ----------

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

function refreshStatus() {
  if (!state.pdf) return setStatus("");
  if (!state.audiveris) return setStatus("Audiveris not installed: showing the PDF only", true);
  const result = state.results.get(state.page);
  const done = [...state.results.values()].filter((r) => !r.error).length;
  const total = state.pdf.numPages;
  const progress = done < total ? ` (${done}/${total} pages read)` : "";
  if (result?.error) return setStatus(`Couldn't read this page: ${result.error}`, true);
  if (result) {
    const n = result.notes.length;
    return setStatus((result.message || `${n} notes on this page`) + progress);
  }
  if (state.busyPage === state.page) return setStatus(`Reading the notes on this page…${progress}`);
  return setStatus(`Waiting to read this page…${progress}`);
}

// ---------- opening a PDF ----------

async function sha256(buffer) {
  if (crypto?.subtle) {
    const hash = await crypto.subtle.digest("SHA-256", buffer);
    return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }
  // crypto.subtle only exists on localhost/https; fall back to a simple hash.
  let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < bytes.length; i++) {
    h1 = Math.imul(h1 ^ bytes[i], 2654435761);
    h2 = Math.imul(h2 ^ bytes[i], 1597334677);
  }
  return ((h1 >>> 0).toString(16).padStart(8, "0") + (h2 >>> 0).toString(16).padStart(8, "0")).repeat(2);
}

async function openFile(file) {
  if (!file) return;
  setStatus("Opening…");
  try {
    const buffer = await file.arrayBuffer();
    const docId = await sha256(buffer);
    const pdf = await pdfjsLib.getDocument({ data: new Uint8Array(buffer) }).promise;
    state.generation++;
    state.pdf = pdf;
    state.docId = docId;
    state.name = file.name;
    state.page = 1;
    state.results = new Map();
    state.busyPage = null;
    $("doc-name").textContent = file.name.replace(/\.pdf$/i, "");
    document.title = `${$("doc-name").textContent} · Sheet Cheat`;
    $("empty").hidden = true;
    $("page-wrap").hidden = false;
    $("page-indicator").hidden = false;
    await renderPage();
    analyseAll(state.generation);
  } catch (err) {
    console.error(err);
    setStatus(`Couldn't open that file: ${err.message || err}`, true);
  }
}

$("file-input").addEventListener("change", (e) => {
  openFile(e.target.files[0]);
  e.target.value = "";
});

stage.addEventListener("dragover", (e) => { e.preventDefault(); stage.classList.add("dragging"); });
stage.addEventListener("dragleave", () => stage.classList.remove("dragging"));
stage.addEventListener("drop", (e) => {
  e.preventDefault();
  stage.classList.remove("dragging");
  const file = [...e.dataTransfer.files].find((f) => /pdf$/i.test(f.type) || /\.pdf$/i.test(f.name));
  openFile(file);
});

// ---------- rendering ----------

async function renderPage() {
  if (!state.pdf) return;
  const pageNo = state.page;
  const page = await state.pdf.getPage(pageNo);
  const base = page.getViewport({ scale: 1 });
  const availW = stage.clientWidth - 24;
  const availH = stage.clientHeight - 24;
  let scale = settings.fit === "width" ? availW / base.width : Math.min(availH / base.height, availW / base.width);
  scale = Math.max(scale, 0.2);
  const viewport = page.getViewport({ scale });
  const dpr = window.devicePixelRatio || 1;

  if (state.renderTask) state.renderTask.cancel();
  canvas.width = Math.floor(viewport.width * dpr);
  canvas.height = Math.floor(viewport.height * dpr);
  canvas.style.width = `${Math.floor(viewport.width)}px`;
  canvas.style.height = `${Math.floor(viewport.height)}px`;
  $("page-wrap").style.width = canvas.style.width;
  $("page-wrap").style.height = canvas.style.height;

  const task = page.render({
    canvasContext: canvas.getContext("2d"),
    viewport,
    transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null,
  });
  state.renderTask = task;
  try {
    await task.promise;
  } catch (err) {
    if (err?.name !== "RenderingCancelledException") console.error(err);
    return;
  }
  if (pageNo !== state.page) return;
  drawOverlay();
  updateNav();
  refreshStatus();
}

function drawOverlay() {
  overlay.replaceChildren();
  overlay.classList.toggle("hidden", !settings.show);
  overlay.classList.toggle("colors", settings.colors);
  const result = state.results.get(state.page);
  if (!result || !result.notes || !settings.show) return;

  const W = canvas.clientWidth;
  const H = canvas.clientHeight;
  const staffSpace = (result.space || 0.008) * H;
  const fontSize = Math.max(10, staffSpace * 1.5 * settings.size);
  const gap = staffSpace * 0.3;

  // Create all labels first so their real sizes can be measured.
  const notes = [...result.notes].sort((a, b) => a.x - b.x || a.y - b.y);
  const labels = notes.map((note) => {
    const { name, octave } = labelFor(note);
    const el = document.createElement("span");
    el.className = "note-label" + (note.grace ? " grace" : "");
    el.dataset.step = note.step;
    el.textContent = name;
    if (settings.octave) {
      const sub = document.createElement("sub");
      sub.textContent = octave;
      el.appendChild(sub);
    }
    el.style.fontSize = `${fontSize}px`;
    overlay.appendChild(el);
    return el;
  });

  // Then place them one by one, left to right, each in the first spot next
  // to its note that doesn't touch a label already placed.
  const placed = [];
  const free = (x, y, w, h) =>
    placed.every((r) => x + w + 1 <= r.x || r.x + r.w + 1 <= x || y + h + 1 <= r.y || r.y + r.h + 1 <= y);
  notes.forEach((note, i) => {
    const el = labels[i];
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    const right = (note.x + note.w) * W + gap;
    const left = note.x * W - gap - w;
    const top = note.y * H - h / 2;
    const candidates = [
      [right, top], [right, top - h * 0.55], [right, top + h * 0.55],
      [right + w * 0.8, top], [right + w * 0.8, top - h * 0.55], [right + w * 0.8, top + h * 0.55],
      [left, top], [left, top - h * 0.55], [left, top + h * 0.55],
    ];
    let spot = candidates.find(([x, y]) => free(x, y, w, h));
    for (let step = 2; !spot; step++) {
      // crowded: keep moving right until there is room (always ends)
      const x = right + step * w * 0.8;
      spot = [[x, top], [x, top - h * 0.55], [x, top + h * 0.55]].find(([cx, cy]) => free(cx, cy, w, h));
    }
    placed.push({ x: spot[0], y: spot[1], w, h });
    el.style.left = `${spot[0]}px`;
    el.style.top = `${spot[1]}px`;
  });
}

// ---------- page turning ----------

function updateNav() {
  const total = state.pdf ? state.pdf.numPages : 0;
  $("prev").disabled = !state.pdf || state.page <= 1;
  $("next").disabled = !state.pdf || state.page >= total;
  $("page-indicator").textContent = `${state.page} / ${total}`;
}

function goTo(page) {
  if (!state.pdf) return;
  page = Math.min(Math.max(page, 1), state.pdf.numPages);
  if (page === state.page) return;
  state.page = page;
  stage.scrollTop = 0;
  updateNav();
  refreshStatus();
  renderPage();
}

$("prev").addEventListener("click", () => goTo(state.page - 1));
$("next").addEventListener("click", () => goTo(state.page + 1));

document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "SELECT" || e.target.type === "range") return;
  const key = e.key;
  if (key === "ArrowRight" || key === "PageDown" || (key === " " && !e.shiftKey)) {
    e.preventDefault();
    goTo(state.page + 1);
  } else if (key === "ArrowLeft" || key === "PageUp" || (key === " " && e.shiftKey)) {
    e.preventDefault();
    goTo(state.page - 1);
  } else if (key === "Home") {
    goTo(1);
  } else if (key === "End" && state.pdf) {
    goTo(state.pdf.numPages);
  }
});

let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(renderPage, 150);
});

// ---------- reading the notes (via the local server + Audiveris) ----------

function nextPageToAnalyse() {
  const total = state.pdf.numPages;
  // the page on screen first, then the ones after it, then the ones before
  for (let i = 0; i < total; i++) {
    const p = ((state.page - 1 + i) % total) + 1;
    if (!state.results.has(p)) return p;
  }
  return null;
}

async function pageAsPng(pageNo) {
  const page = await state.pdf.getPage(pageNo);
  const base = page.getViewport({ scale: 1 });
  let scale = OMR_DPI / 72;
  scale = Math.min(scale, OMR_MAX_SIDE / Math.max(base.width, base.height));
  const viewport = page.getViewport({ scale });
  const c = document.createElement("canvas");
  c.width = Math.round(viewport.width);
  c.height = Math.round(viewport.height);
  const ctx = c.getContext("2d");
  ctx.fillStyle = "white";
  ctx.fillRect(0, 0, c.width, c.height);
  await page.render({ canvasContext: ctx, viewport }).promise;
  return new Promise((resolve) => c.toBlob(resolve, "image/png"));
}

async function analyseAll(generation) {
  try {
    const status = await fetch("/api/status").then((r) => r.json());
    state.audiveris = Boolean(status.audiveris);
  } catch {
    state.audiveris = false;
  }
  refreshStatus();
  if (!state.audiveris) return;

  while (generation === state.generation) {
    const pageNo = nextPageToAnalyse();
    if (pageNo === null) break;
    state.busyPage = pageNo;
    refreshStatus();
    const url = `/api/page/${state.docId}/${pageNo}`;
    let result;
    try {
      let res = await fetch(url);
      if (res.status === 404) {
        const png = await pageAsPng(pageNo);
        if (generation !== state.generation) return;
        res = await fetch(url, { method: "POST", body: png, headers: { "Content-Type": "image/png" } });
      }
      result = await res.json();
      if (!res.ok && !result.error) result = { error: `server error ${res.status}` };
    } catch (err) {
      result = { error: err.message || String(err) };
    }
    if (generation !== state.generation) return;
    if (result.notes?.length) {
      try {
        await snapToHeads(await state.pdf.getPage(pageNo), result);
      } catch (err) {
        console.warn("couldn't snap labels to note heads", err);
      }
      if (generation !== state.generation) return;
    }
    state.results.set(pageNo, result);
    state.busyPage = null;
    if (pageNo === state.page) drawOverlay();
    refreshStatus();
  }
}

fetch("/api/status")
  .then((r) => r.json())
  .then((s) => { $("audiveris-warning").hidden = Boolean(s.audiveris); })
  .catch(() => {});

import { render } from "./synth.js";

const CATEGORIES = ["ui", "game", "alert", "phone", "world"];
const PREF_OF = { ui: "soundUi", game: "soundGame", alert: "soundAlert", phone: "soundPhone", world: "soundWorld" };
const SEEN_MAX = 512;

const S = { ready: false };
const GESTURES = ["pointerdown", "keydown", "touchend", "click"];
const hasWindow = () => typeof window !== "undefined";

/** A fresh engine. Installs the unlock listener only where a window exists (pre-flight F5). Never runs at import. */
export function resetEngine({ logPlays = false } = {}) {
  if (S.listener && hasWindow()) for (const t of GESTURES) window.removeEventListener(t, S.listener, true);
  Object.assign(S, {
    ready: true, ctx: null, master: null, buses: {}, prefs: null, catalog: null, strict: false, oggOk: null,
    buffers: new Map(), failed: new Set(), last: new Map(), voices: [], seen: new Set(), seenOrder: [], plays: 0,
    log: logPlays || (typeof location !== "undefined" && /[?&]soundlog=1/.test(location.search)) ? [] : null,
    listener: null,
  });
  if (!hasWindow()) return;
  S.listener = () => unlock();
  for (const t of GESTURES) window.addEventListener(t, S.listener, true);
  if (S.log) window.__clockworkSoundLog = S.log;
}

/** The first API call (App's `installClickSounds`, a play, a catalogue) installs the engine lazily. */
export function ensure() { if (!S.ready) resetEngine(); }

function unlock() {
  if (!S.ctx) {
    const Ctx = globalThis.AudioContext || globalThis.webkitAudioContext;
    if (!Ctx) return;
    S.ctx = new Ctx();
    S.master = S.ctx.createGain();
    S.master.connect(S.ctx.destination);
    for (const c of CATEGORIES) { S.buses[c] = S.ctx.createGain(); S.buses[c].connect(S.master); }
    try { S.oggOk = new Audio().canPlayType('audio/ogg; codecs="vorbis"') !== ""; } catch { S.oggOk = false; }
    applyLevels();
  }
  if (S.ctx.state !== "running") S.ctx.resume().catch((err) => { if (!S.resumeWarned) { S.resumeWarned = true; console.warn("[sound] resume refused", err); } });
}

function applyLevels() {
  if (!S.ctx || !S.prefs) return;
  const p = S.prefs;
  S.master.gain.setValueAtTime(p.muted ? 0 : p.soundMaster ?? 0.8, S.ctx.currentTime);
  for (const c of CATEGORIES) S.buses[c].gain.setValueAtTime(p[PREF_OF[c]] ?? 1, S.ctx.currentTime);
}
export function setLevels(prefs) { ensure(); S.prefs = prefs; applyLevels(); }
export function installCatalog(catalog, { strict = false } = {}) { ensure(); S.catalog = catalog; S.strict = strict; }
export const limits = () => (S.catalog && S.catalog.limits) || {};
export const playCount = () => S.plays || 0;
/** The Ogg probe's answer once a gesture has run it; null before (Audition's "fallback" mark, pre-flight F29). */
export const oggSupported = () => S.oggOk;

export function markSeen(keys) {
  ensure();
  for (const k of keys || []) remember(String(k));
}
function remember(k) {
  if (S.seen.has(k)) return;
  S.seen.add(k); S.seenOrder.push(k);
  while (S.seenOrder.length > SEEN_MAX) S.seen.delete(S.seenOrder.shift());
}

function note(row) { if (S.log) { S.log.push(row); if (S.log.length > 200) S.log.shift(); } return row; }

export function resolve(event) {
  const cat = S.catalog;
  if (!cat || !cat.enabled) return { why: "unbound" };
  if (!cat.events.includes(event)) {
    if (S.strict) throw new Error(`no such sound event: ${event}`);
    return { why: "unbound" };
  }
  let id = cat.bind[event];
  if (id && typeof id === "object") id = (S.prefs?.soundChoices || {})[event] && id.choices.includes(S.prefs.soundChoices[event]) ? S.prefs.soundChoices[event] : id.default;
  return id && cat.sounds[id] ? { id, row: cat.sounds[id] } : { why: "unbound" };
}

export function play(event, { key, delayMs = 0 } = {}) {
  ensure();
  const base = { t: Date.now(), event, key };
  if (key != null && S.seen.has(String(key))) return note({ ...base, dropped: "seen" });
  const found = resolve(event);
  if (!found.id) return note({ ...base, dropped: found.why });
  if (key != null) remember(String(key));
  const { id, row } = found;
  const entry = { ...base, sound: id, category: row.category };
  if (!S.ctx) return note({ ...entry, dropped: "locked" });       // no gesture yet: dropped, never queued
  if (S.ctx.state !== "running") S.ctx.resume().catch(() => {});  // scheduled anyway; plays on resume (F33)
  const p = S.prefs || {};
  if (p.muted || (p.soundMaster ?? 0.8) === 0 || (p[PREF_OF[row.category]] ?? 1) === 0) return note({ ...entry, dropped: "muted" });
  if (p.quietInterface && !row.essential) return note({ ...entry, dropped: "quiet" });
  const gap = row.throttle_ms ?? S.catalog.limits.throttle_ms ?? 60;
  const now = performance.now();
  if (now - (S.last.get(id) ?? -Infinity) < gap) return note({ ...entry, dropped: "throttled" });
  S.last.set(id, now);
  S.plays = (S.plays || 0) + 1;
  const when = S.ctx.currentTime + delayMs / 1000;
  const out = S.ctx.createGain();
  out.gain.setValueAtTime(row.gain ?? 1, when);
  out.connect(S.buses[row.category]);
  const voice = { sources: [], entry: note({ ...entry }) };
  if (row.synth) voice.sources = render(S.ctx, row.synth, out, when);
  else playFile(row, out, when, voice);
  S.voices.push(voice);
  const cap = S.catalog.limits.voices ?? 8;
  while (S.voices.length > cap) {
    const old = S.voices.shift();
    for (const src of old.sources) { try { src.stop(); } catch { /* already stopped */ } }
    old.entry.stopped = true;
  }
  return voice.entry;
}

function playFile(row, out, when, voice) {
  const fallback = () => { voice.entry.fallback = true; voice.sources = render(S.ctx, row.fallback, out, when); };
  if (!S.oggOk || S.failed.has(row.url)) return fallback();
  const ready = S.buffers.get(row.url);
  if (ready && ready.duration !== undefined) {
    const src = S.ctx.createBufferSource();
    src.buffer = ready;
    src.playbackRate.setValueAtTime(row.rate ?? 1, when);
    src.connect(out);
    src.start(when, (row.start_ms || 0) / 1000);
    voice.sources = [src];
    return undefined;
  }
  fallback();                                            // the first play of a file is its fallback while it loads
  if (!ready) {
    const loading = fetch(row.url).then((r) => r.arrayBuffer()).then((b) => S.ctx.decodeAudioData(b))
      .then((buf) => S.buffers.set(row.url, buf))
      .catch((err) => { S.failed.add(row.url); S.buffers.delete(row.url); console.warn(`[sound] ${row.url} will play its fallback`, err); });
    S.buffers.set(row.url, loading);
  }
  return undefined;
}

export const soundLog = () => (S.log ? S.log.slice() : []);
/** A silent skip worth seeing in the log (useSoundOnChange outside a sent turn, Plan decision 18). */
export function noteSkip(event, why) { note({ t: Date.now(), event, dropped: why }); }

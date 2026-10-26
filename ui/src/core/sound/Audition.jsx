import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { loadPrefs, savePrefs } from "../screens/Settings.jsx";
import { installCatalog, oggSupported, playSound, setLevels } from "./index.js";

// The audition page (?sounds=1, spec §11): every sound of the engine and of every story, played one at a time.
// It PLAYS sounds and edits none: the owner listens, then asks for a change by the key shown on each row.

const GESTURES = ["pointerdown", "keydown", "touchend", "click"];
const EVENT = "audition.play";

const isLeaf = (v) => v === null || typeof v !== "object";
const isFlat = (v) => Array.isArray(v) && v.every(isLeaf);

/** A synth as indented YAML-ish text, for reading rather than for parsing. */
function dump(value, depth = 0) {
  const pad = "  ".repeat(depth);
  if (isLeaf(value)) return JSON.stringify(value);
  if (isFlat(value)) return `[${value.map((v) => JSON.stringify(v)).join(", ")}]`;
  if (Array.isArray(value)) return value.map((v) => `${pad}- ${dump(v, depth + 1).trimStart()}`).join("\n");
  return Object.entries(value).map(([k, v]) => (
    isLeaf(v) || isFlat(v) ? `${pad}${k}: ${dump(v)}` : `${pad}${k}:\n${dump(v, depth + 1)}`
  )).join("\n");
}

/** Every event bound to sound `id`, a chosen-among binding included. */
function eventsFor(bind, id) {
  return Object.entries(bind || {})
    .filter(([, b]) => (b && typeof b === "object" ? b.default === id || (b.choices || []).includes(id) : b === id))
    .map(([e]) => e);
}

function Row({ id, row, scope, events, fallbackKnown, overridesNote, onPlay }) {
  const [copied, setCopied] = useState(false);
  const file = row.file != null;
  const fallback = file && fallbackKnown;
  const prov = row.provenance;
  const copy = () => {
    try {
      Promise.resolve(navigator.clipboard.writeText(row.key)).then(() => setCopied(true), () => {});
    } catch { /* no clipboard: the key is on screen to select */ }
  };
  return (
    <li className="audition__row" data-sound-id={id} data-fallback={fallback ? "true" : undefined}>
      <button type="button" className="audition__play" aria-label={`Play ${id}`} onClick={() => onPlay(scope, id)}>{"▶"}</button>
      <div className="audition__body">
        <div className="audition__head">
          <strong>{row.label || id}</strong> <span className="audition__id">{id}</span>
          <span className="audition__cat">{row.category}</span>
          {overridesNote && row.overrides ? <span className="audition__flag">overrides the engine's</span> : null}
          {fallback ? <span className="audition__flag audition__flag--warn">fallback</span> : null}
        </div>
        <div className="audition__meta">
          {file ? (
            <span>file {row.file}{prov ? ` · ${prov.pack} · ${prov.author} · ${prov.licence}` : ""}{fallback ? " · the synth fallback plays" : ""}</span>
          ) : <span>synth</span>}
          {events.length ? <span> · events: {events.join(", ")}</span> : <span> · bound to no event</span>}
        </div>
        <div className="audition__key">
          <code>{row.key}</code>
          <button type="button" className="audition__copy" onClick={copy}>{copied ? "Copied" : "Copy key"}</button>
        </div>
        <details><summary>Parameters</summary><pre>{dump(row.synth || row.fallback || { file: row.file })}</pre></details>
      </div>
    </li>
  );
}

export default function Audition() {
  const [body, setBody] = useState(null);
  const [failed, setFailed] = useState(false);
  const [filter, setFilter] = useState("");
  const [prefs, setPrefs] = useState(loadPrefs);
  const [unlocked, setUnlocked] = useState(false);
  const [, setProbe] = useState(0);
  const filterRef = useRef(null);
  const timers = useRef([]);

  useEffect(() => {
    let live = true;
    fetch("/api/sounds/catalog")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((b) => { if (live) setBody(b); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, []);

  useEffect(() => {
    // Whichever listener runs first on a gesture, the engine's unlock (which runs the Ogg probe) has run by the next
    // task, so the re-render waits one: it never depends on listener order (a native event can run microtasks between).
    const onGesture = () => {
      timers.current.push(setTimeout(() => { setUnlocked(true); setProbe((n) => n + 1); }, 0));
    };
    for (const t of GESTURES) window.addEventListener(t, onGesture, true);
    const onKey = (e) => {
      if (e.key === "/" && !/INPUT|TEXTAREA/.test(document.activeElement?.tagName || "")) {
        e.preventDefault();
        filterRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      for (const t of GESTURES) window.removeEventListener(t, onGesture, true);
      window.removeEventListener("keydown", onKey);
      timers.current.forEach(clearTimeout);
    };
  }, []);

  useEffect(() => {
    setLevels({ ...prefs, quietInterface: false });
  }, [prefs]);

  // clockwork_prefs is written only when the player changes a level or the mute, never on mount.
  const changePrefs = (next) => { setPrefs(next); savePrefs(next); };

  const scopes = useMemo(() => {
    if (!body) return [];
    const list = [{ scope: "_engine", title: "Engine", data: body.engine }];
    for (const s of body.stories || []) list.push({ scope: s.slug, title: s.title || s.slug, data: s, story: s });
    return list;
  }, [body]);

  const play = useCallback((scopeName, id) => {
    const sc = scopes.find((s) => s.scope === scopeName);
    if (!sc || !sc.data.sounds) return;
    installCatalog({ enabled: true, limits: body.engine.limits || {}, events: [EVENT], bind: { [EVENT]: id }, sounds: sc.data.sounds });
    playSound(EVENT);
  }, [scopes, body]);

  const playEach = (sc) => {
    timers.current.forEach(clearTimeout);
    timers.current = Object.keys(sc.data.sounds || {}).map((id, i) => setTimeout(() => play(sc.scope, id), i * 1000));
  };

  if (failed) return <p className="audition audition__error">The sound list would not load.</p>;
  if (!body) return <p className="audition">Loading the sounds…</p>;

  const q = filter.trim().toLowerCase();
  const fallbackKnown = oggSupported() === false;
  const matches = (id, row, events) => !q || [id, row.label, row.category, ...events].some((t) => String(t || "").toLowerCase().includes(q));

  return (
    <main className="audition">
      <h1>Sounds</h1>
      <p className="audition__hint">Play a sound and ask for a change by its key. This page plays; it does not edit.</p>
      {!unlocked ? <p className="audition__unlock" role="status">Press any key or click to turn the sound on.</p> : null}
      <div className="audition__bar">
        <input
          ref={filterRef} className="audition__filter" type="search" aria-label="Filter sounds"
          placeholder="Filter by id, event, label or category (/)" value={filter} onChange={(e) => setFilter(e.target.value)}
        />
        <label className="audition__master">Master{" "}
          <input
            type="range" min="0" max="1" step="0.05" value={prefs.soundMaster ?? 0.8}
            onChange={(e) => changePrefs({ ...prefs, soundMaster: Number(e.target.value) })}
          />
        </label>
        <label><input type="checkbox" checked={!!prefs.muted} onChange={(e) => changePrefs({ ...prefs, muted: e.target.checked })} /> Mute</label>
      </div>
      {scopes.map((sc) => {
        const sounds = sc.data.sounds || {};
        const rows = Object.entries(sounds)
          .map(([id, row]) => [id, row, eventsFor(sc.data.bind, id)])
          .filter(([id, row, ev]) => matches(id, row, ev));
        const inherits = sc.story && sc.story.declares === false;
        return (
          <section key={sc.scope} className="audition__section" data-scope={sc.scope} aria-label={sc.title}>
            <h2>{sc.title}</h2>
            {sc.story && sc.story.error ? <p className="audition__error" role="alert">This story's sounds.yaml is broken: {sc.story.error}</p> : null}
            {inherits ? <p className="audition__note">Uses the engine's sounds.</p> : null}
            {inherits ? null : (
              <>
                {rows.length ? <button type="button" className="audition__each" onClick={() => playEach(sc)}>Play each</button> : null}
                <ul className="audition__list">
                  {rows.map(([id, row, ev]) => (
                    <Row key={id} id={id} row={row} scope={sc.scope} events={ev} fallbackKnown={fallbackKnown} overridesNote={sc.scope !== "_engine"} onPlay={play} />
                  ))}
                </ul>
              </>
            )}
          </section>
        );
      })}
    </main>
  );
}

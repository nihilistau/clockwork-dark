/**
 * Settings.
 *
 * WHAT THIS REPLACES: four localStorage preferences, none of which reached the
 * engine, plus a "Local services" fieldset gated on a `services` prop that
 * main.jsx never passed — eighteen lines that had never once rendered.
 *
 * config/default.yaml carries roughly twenty-five knobs a player has a real
 * opinion about: whether narration is spoken and in whose voice, whether
 * pictures are generated inside a turn, how much the companion may say, which
 * model narrates — and `world.evil_base_rate_per_day`, which is the difficulty
 * and pace of the entire game and lived only in a checked-in YAML file.
 *
 * Those all round-trip through GET/POST /api/settings, which writes a
 * whitelisted, type-checked, range-clamped subset into config/local.yaml. Two
 * classes of setting are deliberately distinguished on screen: the ones that
 * bite on the next turn, and the ones that need a restart (model binding,
 * transport, context window). A setting that silently did nothing until the
 * next launch is worse than one that says so.
 */
import React, { useEffect, useState } from "react";
import Modal from "../parts/Modal.jsx";
import { fetchSettings, writeSettings } from "../api.js";

export const DEFAULTS = {
  textSize: "normal", // small | normal | large
  reduceMotion: false,
  muted: false,
  showDiceBreakdown: true,
  // Mute was binary; a player who wants narration quieter had to choose
  // between full volume and silence.
  volume: 0.8,
  // The thinking panel is the most interesting thing on screen during a slow
  // local turn, but it is also a model talking to itself. Opt out here.
  showReasoning: true,
  // Sound (v0.24.0): the master and the five categories (spec §7). `volume` stays the narration's own level.
  soundMaster: 0.8,
  soundUi: 0.6,
  soundGame: 0.8,
  soundAlert: 0.9,
  soundPhone: 0.9,
  soundWorld: 0.8,
  quietInterface: false,
  soundChoices: {},
};

/** The Sound fieldset's sliders: [pref key, label]. */
const SOUND_LEVELS = [
  ["soundMaster", "Master"],
  ["soundUi", "Interface"],
  ["soundGame", "Game"],
  ["soundAlert", "Alerts"],
  ["soundPhone", "Phone"],
  ["soundWorld", "World"],
  ["volume", "Narration"],
];

export function loadPrefs() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem("clockwork_prefs") || "{}") };
  } catch {
    return { ...DEFAULTS };
  }
}

export function savePrefs(prefs) {
  try {
    localStorage.setItem("clockwork_prefs", JSON.stringify(prefs));
  } catch {
    /* private browsing — settings just will not persist */
  }
}

function Level({ label, value, onChange }) {
  return (
    <label className="setting">
      <span className="setting__body">
        <span className="setting__label">{label}</span>
        <span className="setting__hint">{Math.round(value * 100)}%</span>
      </span>
      <input
        type="range"
        min="0"
        max="1"
        step="0.05"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={`${label} volume`}
        data-sound="none"
      />
    </label>
  );
}

function Toggle({ label, hint, checked, onChange }) {
  return (
    <label className="setting">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="setting__body">
        <span className="setting__label">{label}</span>
        {hint && <span className="setting__hint">{hint}</span>}
      </span>
    </label>
  );
}

/** One engine setting, rendered from its server-declared spec. */
function EngineField({ spec, value, onChange, readOnly = false }) {
  const id = `set-${spec.key.replace(/\./g, "-")}`;
  const control = () => {
    if (spec.type === "bool") {
      return (
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          disabled={readOnly}
          onChange={(e) => onChange(spec.key, e.target.checked)}
        />
      );
    }
    if (spec.type === "enum") {
      return (
        <select
          id={id}
          className="field__input field__input--short"
          value={String(value ?? "")}
          disabled={readOnly}
          onChange={(e) => onChange(spec.key, e.target.value)}
        >
          {spec.options.map((option) => (
            <option key={option} value={option}>
              {option.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      );
    }
    if (spec.type === "text") {
      return (
        <input
          id={id}
          className="field__input"
          value={String(value ?? "")}
          maxLength={spec.maxlength || 120}
          placeholder="discover automatically"
          disabled={readOnly}
          onChange={(e) => onChange(spec.key, e.target.value)}
        />
      );
    }
    // int and float both get a slider plus the live number. The slider is the
    // point: `evil_base_rate_per_day` is a pace dial, and a bare number box
    // gives no sense of where in the range you are.
    return (
      <span className="setting__slider">
        <input
          id={id}
          type="range"
          min={spec.min}
          max={spec.max}
          step={spec.step || (spec.type === "int" ? 1 : 0.01)}
          value={Number(value ?? spec.min)}
          disabled={readOnly}
          onChange={(e) => onChange(spec.key, Number(e.target.value))}
        />
        <output htmlFor={id}>{value}</output>
      </span>
    );
  };

  return (
    <div className={`setting setting--engine ${spec.restart ? "needs-restart" : ""}`}>
      <label className="setting__body" htmlFor={id}>
        <span className="setting__label">
          {spec.label}
          {spec.restart && <span className="setting__badge">restart</span>}
        </span>
        {spec.hint && <span className="setting__hint">{spec.hint}</span>}
        {spec.marks && (
          <span className="setting__marks">
            {Object.entries(spec.marks).map(([at, word]) => (
              <span key={at}>
                {word} {at}
              </span>
            ))}
          </span>
        )}
      </label>
      {control()}
    </div>
  );
}

export default function Settings({ prefs, onChange, onClose }) {
  const set = (key) => (value) => onChange({ ...prefs, [key]: value });

  const [spec, setSpec] = useState(null);
  const [draft, setDraft] = useState({});
  const [status, setStatus] = useState("");
  const [failed, setFailed] = useState("");

  useEffect(() => {
    let live = true;
    fetchSettings()
      .then((data) => live && setSpec(data))
      .catch(() =>
        // A missing route must leave the client preferences usable rather than
        // blanking the whole panel.
        live && setFailed("The engine settings are unreachable — client preferences still work.")
      );
    return () => {
      live = false;
    };
  }, []);

  // `writable: false` is hosted mode's shape (engine/api/settings.py); absent
  // is local mode's, so the local fixture is untouched (spec §7).
  const writable = spec?.writable !== false;
  const rows = spec?.settings || [];
  const value = (row) => (row.key in draft ? draft[row.key] : row.value);
  const dirty = Object.keys(draft).length > 0;

  function edit(key, next) {
    setDraft((current) => ({ ...current, [key]: next }));
    setStatus("");
  }

  async function commit() {
    setStatus("writing…");
    try {
      const result = await writeSettings(draft);
      setSpec(result);
      setDraft({});
      const notes = Object.values(result.notes || {});
      const restart = result.restart_needed || [];
      setStatus(
        [
          `written to ${result.config_path || spec?.config_path || "the config"}`,
          notes.length ? notes.join("; ") : "",
          restart.length
            ? `${restart.length} setting${restart.length > 1 ? "s take" : " takes"} effect after a restart`
            : "",
        ]
          .filter(Boolean)
          .join(" · ")
      );
    } catch (err) {
      setStatus(`could not write: ${err.message}`);
    }
  }

  async function revert() {
    setStatus("clearing…");
    try {
      const result = await writeSettings({}, { reset: true });
      setSpec(result);
      setDraft({});
      setStatus("back to the shipped defaults");
    } catch (err) {
      setStatus(`could not clear: ${err.message}`);
    }
  }

  return (
    <Modal
      title="Settings"
      onClose={onClose}
      wide
      footer={
        <>
          <span className="settings__status">{status}</span>
          {/* Hosted mode refuses a write (§6.7), so it is not offered. */}
          {writable && (
            <>
              <button type="button" className="btn btn--ghost btn--sm" onClick={revert}>
                Reset to defaults
              </button>
              <button type="button" className="btn" disabled={!dirty} onClick={commit}>
                {dirty ? `Apply ${Object.keys(draft).length}` : "Applied"}
              </button>
            </>
          )}
          <button type="button" className="btn btn--lg" onClick={onClose}>
            Back to the world
          </button>
        </>
      }
    >
      <fieldset className="settings__group">
        <legend className="field__label">Reading</legend>
        <label className="setting">
          <span className="setting__body">
            <span className="setting__label">Text size</span>
          </span>
          <select
            className="field__input field__input--short"
            value={prefs.textSize}
            onChange={(e) => set("textSize")(e.target.value)}
          >
            <option value="small">Small</option>
            <option value="normal">Normal</option>
            <option value="large">Large</option>
          </select>
        </label>

        <Toggle
          label="Reduce motion"
          hint="Stops the cursor blink, the turning gear and all crossfades."
          checked={prefs.reduceMotion}
          onChange={set("reduceMotion")}
        />
        <Toggle
          label="Show dice breakdown"
          hint="Every modifier that went into a roll, so a failure reads as a reason."
          checked={prefs.showDiceBreakdown}
          onChange={set("showDiceBreakdown")}
        />
        <Toggle
          label="Show the world thinking"
          hint="The narrator's reasoning, live, while it decides what happens to you."
          checked={prefs.showReasoning}
          onChange={set("showReasoning")}
        />
      </fieldset>

      <fieldset className="settings__group">
        <legend className="field__label">Sound</legend>
        {SOUND_LEVELS.map(([key, label]) => (
          <Level key={key} label={label} value={prefs[key] ?? DEFAULTS[key] ?? 0.8} onChange={set(key)} />
        ))}
        <Toggle label="Mute all sound" hint="Silences every effect and the narration." checked={prefs.muted} onChange={set("muted")} />
        <Toggle
          label="Quiet interface"
          hint="Only alerts and messages make a sound."
          checked={Boolean(prefs.quietInterface)}
          onChange={set("quietInterface")}
        />
        <a href="/?sounds=1" target="_blank" rel="noopener">
          Listen to every sound
        </a>
      </fieldset>

      {failed && <p className="overlay__error">{failed}</p>}
      {!spec && !failed && <p className="overlay__empty">Reading the config…</p>}

      {(spec?.groups || []).map((group) => (
        <fieldset key={group} className="settings__group">
          <legend className="field__label">{group}</legend>
          {rows
            .filter((row) => row.group === group)
            .map((row) => (
              <EngineField key={row.key} spec={row} value={value(row)} onChange={edit} readOnly={!writable} />
            ))}
        </fieldset>
      ))}

      {spec && (
        <p className="setting__hint settings__footnote">
          {writable ? (
            <>
              These are written to {spec.config_path ? <code>{spec.config_path}</code> : "the local config"}, which
              is gitignored and layered over the shipped defaults. Only the keys listed here can be written, and every
              number is clamped to its range, so nothing you can set from this panel can make a run unplayable. Run{" "}
              <code>python scripts/doctor.py</code> to see what is actually running on this machine.
            </>
          ) : (
            // Hosted mode: the path is on the operator's machine and is not
            // sent (engine/api/settings.py), and the doctor is theirs to run.
            "These are set by the operator of this server."
          )}
        </p>
      )}
    </Modal>
  );
}

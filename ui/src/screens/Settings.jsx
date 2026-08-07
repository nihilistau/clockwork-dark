/**
 * Settings.
 *
 * Everything here is a CLIENT preference, persisted to localStorage. Server
 * settings (live image generation, TTS) are deliberately absent: they are
 * machine-level decisions with real cost, they belong in config/local.yaml,
 * and a toggle here would imply the game can turn on a service it cannot see.
 * The panel says so rather than pretending.
 */
import React from "react";
import Modal from "../parts/Modal.jsx";

export const DEFAULTS = {
  textSize: "normal", // small | normal | large
  reduceMotion: false,
  muted: false,
  showDiceBreakdown: true,
};

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

export default function Settings({ prefs, onChange, onClose, services }) {
  const set = (key) => (value) => onChange({ ...prefs, [key]: value });

  return (
    <Modal
      title="Settings"
      onClose={onClose}
      footer={
        <button type="button" className="btn btn--lg" onClick={onClose}>
          Back to the world
        </button>
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
          label="Mute narration audio"
          checked={prefs.muted}
          onChange={set("muted")}
        />
      </fieldset>

      {services && (
        <fieldset className="settings__group">
          <legend className="field__label">Local services</legend>
          <p className="setting__hint">
            These are machine settings, not game settings — change them in{" "}
            <code>config/local.yaml</code> and restart. Run{" "}
            <code>python scripts/doctor.py</code> to see what is running.
          </p>
          <ul className="settings__services">
            {Object.entries(services).map(([name, detail]) => (
              <li key={name}>
                <span className="settings__service">{name}</span>
                <span className="setting__hint">{detail}</span>
              </li>
            ))}
          </ul>
        </fieldset>
      )}
    </Modal>
  );
}

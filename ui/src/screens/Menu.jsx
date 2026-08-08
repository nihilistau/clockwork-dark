/**
 * The pause menu (Esc).
 *
 * WHAT THIS CLOSES: there was no menu. The footer had six unlabelled glyphs,
 * Settings held four localStorage toggles, and the things a player reaches for
 * when they stop playing — save this, name it, load another, start again, walk
 * away, what were the keys again — had no home at all. `1`–`4` already picked
 * choices and nothing on screen said so.
 *
 * The evil phase lives up here too. It drives the entire palette and every
 * line the Storyteller writes, and the only place it appeared was a
 * parenthetical in the save list.
 */
import React, { useEffect, useState } from "react";
import Modal from "../parts/Modal.jsx";
import { prettyPlace } from "../parts/Chrome.jsx";
import { fetchGames } from "../api.js";

// Mirrors the flag in parts/Onboarding.jsx. Duplicated rather than imported so
// this screen does not reach into a component it does not own; if that key ever
// moves, both call sites are one grep apart.
const ONBOARD_FLAG = "clockwork_onboarded";

export const PHASE_COPY = {
  dormant: {
    word: "Dormant",
    line: "The world is behaving. Wheat, weather, gossip, bread.",
  },
  stirring: {
    word: "Stirring",
    line: "Something under the floor of things has begun to keep time.",
  },
  spreading: {
    word: "Spreading",
    line: "It is out of the forest now, and it is not in a hurry.",
  },
  consuming: {
    word: "Consuming",
    line: "There is no hour left that is not this hour.",
  },
};

const KEYS = [
  ["1 – 4", "Take the numbered choice"],
  ["Esc", "This menu, or close whatever is open"],
  ["I", "Open the pack"],
  ["J", "Journal"],
  ["C", "Codex"],
  ["B", "Barter"],
  ["/", "Jump to the compose box"],
  ["Enter", "Send what you typed"],
];

function Row({ label, hint, onClick, tone = "", disabled = false }) {
  return (
    <button
      type="button"
      className={`menurow ${tone ? `menurow--${tone}` : ""}`}
      onClick={onClick}
      disabled={disabled}
    >
      <span className="menurow__label">{label}</span>
      {hint && <span className="menurow__hint">{hint}</span>}
    </button>
  );
}

export default function Menu({
  world,
  phase,
  saveId,
  connected,
  prefs,
  onChangePrefs,
  onResume,
  onSaveNow,
  onOpenSaves,
  onOpenSettings,
  onNewRun,
  onAbandon,
}) {
  const [slot, setSlot] = useState("");
  const [saved, setSaved] = useState("");
  const [games, setGames] = useState(null);
  const [confirmAbandon, setConfirmAbandon] = useState(false);

  useEffect(() => {
    let live = true;
    fetchGames()
      .then((data) => live && setGames(data))
      .catch(() => {
        /* the catalogue is a nicety; the menu still works without it */
      });
    return () => {
      live = false;
    };
  }, []);

  const active = (games?.games || []).find((g) => g.active) || null;
  const copy = PHASE_COPY[phase] || PHASE_COPY.dormant;

  async function saveNow() {
    setSaved("saving…");
    try {
      await onSaveNow(slot.trim());
      setSaved("written");
    } catch (err) {
      setSaved(`could not save: ${err.message}`);
    }
  }

  function replayOnboarding() {
    try {
      window.localStorage.removeItem(ONBOARD_FLAG);
      setSaved("the opening cards will show next time you begin");
    } catch {
      /* private browsing — they show every time anyway */
    }
  }

  return (
    <Modal
      title="Paused"
      onClose={onResume}
      wide
      footer={
        <button type="button" className="btn btn--lg" onClick={onResume}>
          Back to the world
        </button>
      }
    >
      {/* The phase, said out loud. It has driven the palette since PR4 and the
          player has never been told what it was. */}
      <div className={`phaseband phaseband--${phase || "dormant"}`}>
        <span className="phaseband__kicker">The pattern is</span>
        <span className="phaseband__word">{copy.word}</span>
        <span className="phaseband__line">{copy.line}</span>
      </div>

      <div className="menu__meta">
        <span>
          {world?.player_name || "Traveler"} the {world?.archetype || "wayfarer"}
        </span>
        <span>
          Day {world?.world_day ?? 1} · {prettyPlace(world?.location_id || "—")}
        </span>
        <span>{world?.turn_number ?? 0} turns</span>
        <span className={connected ? "" : "is-warn"}>
          {connected ? "connected" : "reconnecting"}
        </span>
      </div>

      <div className="menu__cols">
        <section className="menu__col">
          <h3 className="menu__head">The run</h3>
          <div className="menu__rows">
            <Row label="Resume" hint="Esc" onClick={onResume} />
            <Row label="Load another run" onClick={onOpenSaves} />
            <Row label="Settings" hint="voice, pictures, pace" onClick={onOpenSettings} />
            <Row
              label="Begin a new run"
              hint="this one keeps its save"
              onClick={onNewRun}
            />
            {confirmAbandon ? (
              <Row
                label="Yes — abandon it"
                hint="the save stays on disk; this browser forgets it"
                tone="danger"
                onClick={onAbandon}
              />
            ) : (
              <Row
                label="Abandon this run"
                tone="danger"
                onClick={() => setConfirmAbandon(true)}
              />
            )}
          </div>

          <h3 className="menu__head">Save now</h3>
          <div className="menu__save">
            <input
              className="field__input"
              value={slot}
              onChange={(e) => setSlot(e.target.value.slice(0, 32))}
              placeholder="name this save (optional)"
              aria-label="Save slot name"
            />
            <button type="button" className="btn btn--sm" onClick={saveNow} disabled={!saveId}>
              Write
            </button>
          </div>
          {saved && <p className="menu__note">{saved}</p>}
        </section>

        <section className="menu__col">
          <h3 className="menu__head">Sound</h3>
          <label className="setting">
            <span className="setting__body">
              <span className="setting__label">Volume</span>
              <span className="setting__hint">
                {prefs.muted ? "muted" : `${Math.round(prefs.volume * 100)}%`}
              </span>
            </span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={prefs.volume}
              disabled={prefs.muted}
              onChange={(e) =>
                onChangePrefs({ ...prefs, volume: Number(e.target.value) })
              }
              aria-label="Narration volume"
            />
          </label>
          <label className="setting">
            <input
              type="checkbox"
              checked={prefs.muted}
              onChange={(e) => onChangePrefs({ ...prefs, muted: e.target.checked })}
            />
            <span className="setting__body">
              <span className="setting__label">Mute entirely</span>
            </span>
          </label>

          <h3 className="menu__head">Keys</h3>
          <dl className="keymap">
            {KEYS.map(([key, what]) => (
              <div key={key} className="keymap__row">
                <dt>
                  <kbd>{key}</kbd>
                </dt>
                <dd>{what}</dd>
              </div>
            ))}
          </dl>

          <h3 className="menu__head">About</h3>
          <p className="menu__about">
            <b>{active?.title || "The Clockwork Dark"}</b>
            {active?.version ? ` v${active.version}` : ""}
            {active?.blurb ? <span className="menu__blurb">{active.blurb}</span> : null}
          </p>
          <button type="button" className="btn btn--sm btn--ghost" onClick={replayOnboarding}>
            Show the opening cards again
          </button>
        </section>
      </div>
    </Modal>
  );
}

/**
 * The play screen.
 *
 * Three columns on desktop; a tab bar on narrow viewports. The old stylesheet
 * did `display: none` on the assistant AND stats panels under 900px, so a
 * phone player lost health, stamina, gold, inventory and the companion
 * entirely. That is a correctness bug, not a layout preference.
 *
 * When `world.encounter` is non-empty the encounter takes the top of the main
 * column in place of the scene still, and its engine-authored approaches
 * replace the Storyteller's choices. Both lists on screen at once would offer
 * the player two parallel action sets, only one of which the engine will
 * honour.
 */
import React, { useEffect, useRef, useState } from "react";

import AssistantColumn from "../parts/AssistantColumn.jsx";
import ChoiceRow from "../parts/ChoiceRow.jsx";
import DiceToast from "../parts/DiceToast.jsx";
import EncounterPanel from "../parts/EncounterPanel.jsx";
import NarrativeLog from "../parts/NarrativeLog.jsx";
import SceneVisual from "../parts/SceneVisual.jsx";
import Sheet from "../parts/Sheet.jsx";
import { Footer, Header } from "../parts/Chrome.jsx";
import { PHASE_COPY } from "./Menu.jsx";

const TABS = [
  { id: "scene", label: "Scene" },
  { id: "sheet", label: "Sheet" },
  { id: "assistant", label: "Companion" },
];

/**
 * The model, thinking, live.
 *
 * On this hardware the first narration token arrives 10-14 seconds into a
 * turn. The backend has always streamed reasoning on a channel separate from
 * narration and NOTHING CONSUMED IT, so those seconds were a blank screen with
 * three bouncing dots on it. This is the same three dots with the machine's
 * actual deliberation under them, and it folds itself away the moment there
 * are words to read.
 */
function ReasoningPanel({ text, open, busy, onToggle }) {
  const tail = useRef(null);

  // Follow the stream. Reasoning is long and the interesting part is always
  // the last line, not the first.
  useEffect(() => {
    if (open && tail.current) tail.current.scrollTop = tail.current.scrollHeight;
  }, [text, open]);

  if (!text && !busy) return null;

  return (
    <section className={`reasoning ${open ? "is-open" : "is-collapsed"}`}>
      <button
        type="button"
        className="reasoning__toggle"
        aria-expanded={open}
        onClick={onToggle}
        disabled={!text}
      >
        <span className="thinking__dot" />
        <span className="thinking__dot" />
        <span className="thinking__dot" />
        <span className="reasoning__label">
          {busy ? "the world is deciding" : "what the world was thinking"}
        </span>
        {text ? <span className="reasoning__chevron" aria-hidden="true">{open ? "▾" : "▸"}</span> : null}
      </button>

      {open && text && (
        <div className="reasoning__body" ref={tail} role="log" aria-live="off">
          <p className="reasoning__text">{text}</p>
        </div>
      )}
    </section>
  );
}

export default function Scene({ state, onChoose, onCustom, onOpenSaves, onOpenSettings,
                                onOpenJournal, onOpenCodex, onOpenTrade, onOpenPack,
                                onOpenMenu, onToggleReasoning,
                                muted, onToggleMute, showDiceBreakdown = true,
                                showReasoning = true, composeRef }) {
  const [tab, setTab] = useState("scene");
  const [text, setText] = useState("");

  const encounter = state.world?.encounter || {};
  const inEncounter = Object.keys(encounter).length > 0;
  const approaches = encounter.approaches || [];

  function submitCustom(event) {
    event.preventDefault();
    const value = text.trim();
    if (!value || state.busy) return;
    setText("");
    onCustom(value);
  }

  return (
    <div className="scene" data-tab={tab}>
      {/* The evil phase rides in the header's right cluster, beside the world
          clock. It had its own `.chromebar` band, which spent a whole row of a
          768px screen on one pill -- and the scene column only had 567px to
          divide between the art, the log, the choices and the compose box.
          Menu moved to the footer glyph row, where the other controls are. */}
      <Header
        world={state.world}
        phase={state.phase}
        phaseCopy={PHASE_COPY[state.phase] || PHASE_COPY.dormant}
        onOpenMenu={onOpenMenu}
      />

      <main className="scene__grid">
        <div className="scene__col scene__col--assistant">
          <AssistantColumn
            assistant={state.assistant}
            presence={state.presence}
            formHistory={state.formHistory}
            phase={state.phase}
            busy={state.busy}
          />
        </div>

        <section className="scene__col scene__col--main">
          {inEncounter ? (
            <EncounterPanel
              encounter={encounter}
              world={state.world}
              phase={state.phase}
              sceneImage={state.sceneImage}
              busy={state.busy}
              // An approach is an ordinary turn: its own text goes over as a
              // custom action and the Storyteller calls encounter_approach.
              onTake={(approach) => onCustom(approach.text)}
            />
          ) : (
            <SceneVisual world={state.world} imageUrl={state.sceneImage} phase={state.phase} />
          )}

          <NarrativeLog entries={state.log} />

          {/* The old bare "the world is deciding" indicator is now the header
              of the reasoning panel, so the same three dots either sit there
              alone or open onto the model's actual deliberation. */}
          {showReasoning ? (
            <ReasoningPanel
              text={state.reasoning}
              open={state.reasoningOpen}
              busy={state.busy}
              onToggle={onToggleReasoning}
            />
          ) : (
            state.busy && (
              <p className="thinking" role="status">
                <span className="thinking__dot" />
                <span className="thinking__dot" />
                <span className="thinking__dot" />
                <span className="thinking__label">the world is deciding</span>
              </p>
            )
          )}

          {/* Suppressed only when the engine has offered approaches of its
              own; an encounter with an empty approach list still needs the
              narrator's choices or the player has no move at all. */}
          {!(inEncounter && approaches.length > 0) && (
            <ChoiceRow choices={state.choices} busy={state.busy} onChoose={onChoose} />
          )}

          <form className="compose" onSubmit={submitCustom}>
            <input
              className="compose__input"
              ref={composeRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Or say what you do…  (press / to jump here, Esc for the menu)"
              disabled={state.busy}
              aria-label="Custom action"
            />
            <button type="submit" className="btn" disabled={state.busy || !text.trim()}>
              Send
            </button>
          </form>
        </section>

        <div className="scene__col scene__col--sheet">
          <Sheet world={state.world} sessionId={state.sessionId} onOpenPack={onOpenPack} />
        </div>
      </main>

      <nav className="tabbar" aria-label="Panels">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`tabbar__btn ${tab === t.id ? "is-active" : ""}`}
            aria-pressed={tab === t.id}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <Footer
        world={state.world}
        connected={state.connected}
        error={state.error}
        onOpenSaves={onOpenSaves}
        onOpenSettings={onOpenSettings}
        onOpenJournal={onOpenJournal}
        onOpenCodex={onOpenCodex}
        onOpenTrade={onOpenTrade}
        // The pack and the pause menu were keyboard-only (I and Esc), which is
        // undiscoverable -- Footer already draws the buttons and guards on
        // these two props being present.
        onOpenPack={onOpenPack}
        onOpenMenu={onOpenMenu}
        muted={muted}
        onToggleMute={onToggleMute}
      />

      <DiceToast dice={state.dice} showBreakdown={showDiceBreakdown} />
    </div>
  );
}

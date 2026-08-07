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
import React, { useState } from "react";

import AssistantColumn from "../parts/AssistantColumn.jsx";
import ChoiceRow from "../parts/ChoiceRow.jsx";
import DiceToast from "../parts/DiceToast.jsx";
import EncounterPanel from "../parts/EncounterPanel.jsx";
import NarrativeLog from "../parts/NarrativeLog.jsx";
import SceneVisual from "../parts/SceneVisual.jsx";
import Sheet from "../parts/Sheet.jsx";
import { Footer, Header } from "../parts/Chrome.jsx";

const TABS = [
  { id: "scene", label: "Scene" },
  { id: "sheet", label: "Sheet" },
  { id: "assistant", label: "Companion" },
];

export default function Scene({ state, onChoose, onCustom, onOpenSaves, onOpenSettings,
                                onOpenJournal, onOpenCodex, onOpenTrade,
                                muted, onToggleMute, showDiceBreakdown = true }) {
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
      <Header world={state.world} phase={state.phase} />

      <main className="scene__grid">
        <div className="scene__col scene__col--assistant">
          <AssistantColumn assistant={state.assistant} phase={state.phase} />
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

          {state.busy && (
            <p className="thinking" role="status">
              <span className="thinking__dot" />
              <span className="thinking__dot" />
              <span className="thinking__dot" />
              <span className="thinking__label">the world is deciding</span>
            </p>
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
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Or say what you do…"
              disabled={state.busy}
              aria-label="Custom action"
            />
            <button type="submit" className="btn" disabled={state.busy || !text.trim()}>
              Send
            </button>
          </form>
        </section>

        <div className="scene__col scene__col--sheet">
          <Sheet world={state.world} />
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
        muted={muted}
        onToggleMute={onToggleMute}
      />

      <DiceToast dice={state.dice} showBreakdown={showDiceBreakdown} />
    </div>
  );
}

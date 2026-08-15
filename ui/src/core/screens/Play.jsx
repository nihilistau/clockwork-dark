/**
 * The play screen.
 *
 * Three columns on desktop; a tab bar on narrow viewports. The old stylesheet
 * did `display: none` on the assistant AND stats panels under 900px, so a
 * phone player lost health, stamina, gold, inventory and the companion
 * entirely. That is a correctness bug, not a layout preference.
 *
 * WHAT THIS SCREEN NOW KNOWS
 * --------------------------
 * Nothing about any story. It owns the frame -- chrome, three columns, the tab
 * bar, the log, the choices, the compose box, the thinking panel -- and asks the
 * plugin to fill four slots:
 *
 *   Aside    the left column          (default: empty, and the column collapses)
 *   Stage    above the log            (default: nothing)
 *   Ledger   the right column         (default: the declared-meter sheet)
 *   Toast    a floating layer         (default: nothing)
 *
 * The flagship puts its companion, its scene still / encounter panel, its
 * hand-built character sheet and its dice rail in those four. It used to import
 * all four by name from here, which is what made this file "Scene.jsx, the
 * Clockwork play screen" rather than a play screen.
 *
 * `hideChoices` is the one behavioural hook: the flagship suppresses the
 * narrator's choices while an encounter offers engine-authored approaches,
 * because both lists on screen at once would offer the player two parallel
 * action sets and the engine only honours one.
 *
 * `overlays` arrives ALREADY FILTERED by App -- an entry may declare
 * `when(state)`, and a story whose payload does not carry the key an overlay
 * reads must not get a footer button for it. It defaults to the story's whole
 * list so this screen still renders on its own in a fixture.
 */
import React, { useState } from "react";

import ChoiceRow from "../parts/ChoiceRow.jsx";
import MicButton from "../parts/MicButton.jsx";
import NarrativeLog from "../parts/NarrativeLog.jsx";
import ReasoningPanel, { Thinking } from "../parts/ReasoningPanel.jsx";
import { MeterSheet } from "../parts/Meters.jsx";
import { Footer, Header } from "../parts/Chrome.jsx";

const TABS = [
  { id: "scene", label: "Scene" },
  { id: "sheet", label: "Sheet" },
  // Id kept as `assistant` because the responsive rules key off
  // `.scene[data-tab="assistant"]`; the LABEL is the story's to override.
  { id: "assistant", label: "Companion" },
];

export default function Play({
  state,
  story,
  overlays = story.overlays,
  onChoose,
  onCustom,
  onRetry,
  onOpenSaves,
  onOpenSettings,
  onOpenOverlay,
  onOpenMenu,
  onToggleReasoning,
  muted,
  onToggleMute,
  showDiceBreakdown = true,
  showReasoning = true,
  composeRef,
  // True while an overlay or the pause menu owns the screen. Play stays mounted
  // underneath them, so the choice row's window key listener needs to know.
  blocked = false,
}) {
  const [tab, setTab] = useState("scene");
  const [text, setText] = useState("");

  const Aside = story.Aside || null;
  const Stage = story.Stage || null;
  const Ledger = story.Ledger || MeterSheet;
  const Toast = story.Toast || null;
  const Mark = story.Mark || null;
  const Badge = story.HeaderBadge || null;

  // One props object for every slot, so a story implements only what it needs.
  const slot = {
    state,
    busy: state.busy,
    onCustom,
    onChoose,
    onOpenOverlay,
    onOpenMenu,
    showDiceBreakdown,
  };

  const hidden = story.hideChoices ? story.hideChoices(state) : false;

  function submitCustom(event) {
    event.preventDefault();
    const value = text.trim();
    if (!value || state.busy) return;
    setText("");
    onCustom(value);
  }

  /**
   * A transcript joins what is already typed; it never replaces it and never
   * sends. Focus moves to the box with the caret at the end, because the point
   * of not auto-submitting is that the player reads it first -- and reading it
   * is only useful if correcting it is one keystroke away.
   */
  function acceptTranscript(transcript) {
    setText((current) => (current.trim() ? `${current.trim()} ${transcript}` : transcript));
    const box = composeRef?.current;
    if (box) {
      box.focus();
      requestAnimationFrame(() => {
        const end = box.value.length;
        box.setSelectionRange?.(end, end);
      });
    }
  }

  return (
    <div className="scene" data-tab={tab} data-aside={Aside ? "on" : "off"}>
      <Header
        world={state.world}
        title={story.title}
        mark={Mark ? <Mark {...slot} /> : null}
        badge={Badge ? <Badge {...slot} /> : null}
      />

      <main className="scene__grid">
        <div className="scene__col scene__col--assistant">
          {Aside && <Aside {...slot} />}
        </div>

        <section className="scene__col scene__col--main">
          {Stage && <Stage {...slot} />}

          <NarrativeLog entries={state.log} busy={state.busy} />


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
            state.busy && <Thinking />
          )}

          {!hidden && (
            <ChoiceRow
              choices={state.choices}
              busy={state.busy}
              blocked={blocked}
              onChoose={onChoose}
              // A turn that produced no choices is a real state -- an
              // ungrammared answer, a scene that ends on a question, a
              // narrator that simply offered none -- and the row used to
              // render `null` for it, so the space above the compose box went
              // blank and the game looked broken rather than open. It is only
              // an empty state once the turn has SETTLED: mid-turn there is
              // nothing missing yet.
              settled={!state.busy && state.log.length > 0}
            />
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
            <MicButton
              sessionId={state.sessionId}
              disabled={state.busy || !state.sessionId}
              onTranscript={acceptTranscript}
            />
            <button type="submit" className="btn" disabled={state.busy || !text.trim()}>
              Send
            </button>
          </form>
        </section>

        <div className="scene__col scene__col--sheet">
          <Ledger {...slot} />
        </div>
      </main>

      <nav className="tabbar" aria-label="Panels">
        {TABS.filter((t) => t.id !== "assistant" || Aside).map((t) => (
          <button
            key={t.id}
            type="button"
            className={`tabbar__btn ${tab === t.id ? "is-active" : ""}`}
            aria-pressed={tab === t.id}
            onClick={() => setTab(t.id)}
          >
            {t.id === "assistant" ? story.asideLabel || t.label : t.label}
          </button>
        ))}
      </nav>

      <Footer
        world={state.world}
        connected={state.connected}
        error={state.error}
        onRetry={onRetry}
        canRetry={!state.busy}
        overlays={overlays}
        onOpenOverlay={onOpenOverlay}
        onOpenSaves={onOpenSaves}
        onOpenSettings={onOpenSettings}
        onOpenMenu={onOpenMenu}
        muted={muted}
        onToggleMute={onToggleMute}
      />

      {Toast && <Toast {...slot} />}
    </div>
  );
}

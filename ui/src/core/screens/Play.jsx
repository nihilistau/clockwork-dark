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
 *   Stage    above the log            (default: nothing, or core's ScenePlate
 *                                      for a plugin that sets `defaultStage`)
 *   Ledger   the right column         (default: the declared-meter sheet)
 *   Toast    a floating layer         (default: nothing)
 *
 * THE MAIN COLUMN IS NAMED AREAS (v0.21.0, spec §3.1): `.stage-area`, the
 * deck's `.beatframe` (only while one is live), `.log`, `.think-area`,
 * `.shelf`, `.choices-area` and the compose form, always in that order, each
 * placed by its grid-area name. Before, the grid gave its FIRST two children
 * the flexible rows whatever they were, so a stage-less story's log took the
 * picture's row and an optional panel took the log's -- and painted over the
 * choices (F1). `data-stage="off"` collapses the stage track to 0.
 *
 * The flagship puts its companion, its scene still / encounter panel, its
 * hand-built character sheet and its dice rail in those four. It used to import
 * all four by name from here, which is what made this file "Scene.jsx, the
 * Clockwork play screen" rather than a play screen.
 *
 * ENGINE PANELS (v0.21.0, spec §2). Beside the four slots, core draws the
 * engine's own panels (core/panels/registry.js) in five regions: the header's
 * chips, the stage, the shelf, a `.ledger-panels` list under the Ledger, and
 * the toast layer (laid over the main column's stage and log rows). Which
 * ones, and where, is `resolvePanels(story)`: the
 * manifest's `ui.panels`, or the data-gated defaults, minus the plugin's
 * `ownsPanels`.
 *
 * HIDDEN CHOICES ARE DERIVED (v0.21.0, spec §2.3, rule 1). An approach button
 * presses the narrator's choice that carries its `encounter` intent, so that
 * choice is hidden from the row -- and ONLY that choice: a narrator choice
 * that is not an approach stays. With core's encounter panel on screen the
 * hidden set is `matchedChoiceIds`; a plugin that draws its own approaches
 * says which ids through `hideChoices` (the flagship and NEON CITY return the
 * same set). When every choice matched, the row goes and the approaches take
 * the digits (`bindDigits`).
 *
 * `overlays` arrives ALREADY FILTERED by App -- an entry may declare
 * `when(state)`, and a story whose payload does not carry the key an overlay
 * reads must not get a footer button for it. It defaults to the story's whole
 * list so this screen still renders on its own in a fixture.
 */
import React, { useCallback, useMemo, useState } from "react";

import BeatFrame from "../parts/BeatFrame.jsx";
import ChoiceRow from "../parts/ChoiceRow.jsx";
import MicButton from "../parts/MicButton.jsx";
import NarrativeLog from "../parts/NarrativeLog.jsx";
import ReasoningPanel, { Thinking } from "../parts/ReasoningPanel.jsx";
import ScenePlate from "../parts/ScenePlate.jsx";
import { MeterSheet } from "../parts/Meters.jsx";
import { Footer, Header } from "../parts/Chrome.jsx";
import { COARSE_QUERY, NARROW_QUERY, useMedia } from "../hooks/useMedia.js";
import { OPEN_EVENT } from "../panels/Panel.jsx";
import { matchedChoiceIds } from "../panels/approaches.js";
import { resolvePanels } from "../panels/resolve.js";
import { controlsLive } from "../store.js";

const TABS = [
  { id: "scene", label: "Scene" },
  { id: "sheet", label: "Sheet" },
  // Id kept as `assistant` because the responsive rules key off
  // `.scene[data-tab="assistant"]`; the LABEL is the story's to override.
  { id: "assistant", label: "Companion" },
];

/** One region's panels. A panel not built yet (`Component` null) renders nothing. */
function Region({ panels, props }) {
  return panels
    .filter((panel) => panel.Component)
    .map((panel) => <panel.Component key={panel.id} {...props} region={panel.region} />);
}

/**
 * The ids of the narrator's choices to hide (plan decision 10). A plugin's own
 * `hideChoices` wins: `true` hides the row, a falsy answer nothing, an
 * iterable exactly those ids. Otherwise, with core's encounter panel on
 * screen, exactly the choices it presses (spec §2.3) -- never a choice that
 * is not an approach, and nothing at all when nothing matched.
 */
function hiddenChoiceIds(story, state, encounterOn) {
  if (story.hideChoices) {
    const said = story.hideChoices(state);
    if (said === true) return new Set((state.choices || []).map((choice) => choice.id));
    return new Set(said || []);
  }
  return encounterOn ? matchedChoiceIds(state.world?.encounter, state.choices) : new Set();
}

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
  const narrow = useMedia(NARROW_QUERY);
  const coarse = useMedia(COARSE_QUERY);
  // Resolved once per story: the declaration and the plugin do not change
  // while a run plays (spec §2.2).
  const regions = useMemo(() => resolvePanels(story), [story]);
  // Every control is off unless the link is live and no turn is running
  // (spec §6.3, F5): one selector, so a chip, an approach and the compose
  // box can never disagree about whether a press would reach the server.
  const off = !controlsLive(state);

  /**
   * A header chip's press: open the panel it names if it is collapsed, switch
   * to the Sheet tab on a phone only when the panel lives in the ledger (a
   * shelf panel is on the Scene tab), then focus its heading.
   */
  const openSheetTo = useCallback(
    (id) => {
      if (narrow && regions.ledger.some((panel) => panel.id === id)) setTab("sheet");
      window.dispatchEvent(new CustomEvent(OPEN_EVENT, { detail: id }));
      requestAnimationFrame(() => document.getElementById(`panel-${id}-title`)?.focus());
    },
    [narrow, regions]
  );

  const Aside = story.Aside || null;
  const Ledger = story.Ledger || MeterSheet;
  const Toast = story.Toast || null;
  // The stage: the plugin's, else core's scene plate for a plugin that asks
  // for it (`defaultStage`), else none -- and then the column's stage track
  // is 0 (`data-stage="off"`), which is THE LONG CON's look (spec §3.3).
  const Stage = story.Stage || (story.defaultStage ? ScenePlate : null);
  // A stage panel (`people`, when a story puts it there) turns the stage
  // track on too, plugin Stage or none (plan decision 8).
  const stageOn = Boolean(Stage) || regions.stage.some((panel) => panel.Component);
  const Mark = story.Mark || null;
  const Badge = story.HeaderBadge || null;

  // One props object for every slot, so a story implements only what it needs.
  const slot = {
    state,
    busy: state.busy,
    // The link's answer too (spec §6.3): `busy` still means "a turn is
    // running" (the assistant column reads it so). A plugin's own turn
    // controls read this, aria-disabled while it is true (§8.2): the
    // flagship's and NEON CITY's encounter approaches (their Stage slots).
    controlsOff: off,
    onCustom,
    onChoose,
    onOpenOverlay,
    onOpenMenu,
    showDiceBreakdown,
  };

  // The engine panels' props (registry.js): the slot's state and handlers,
  // plus what a panel needs to fit where it is drawn.
  const encounterOn = regions.shelf.some((panel) => panel.id === "encounter" && panel.Component);
  // Memoised on the choices: ChoiceRow's key binding and its "more below"
  // measure re-run whenever the array it is handed changes identity.
  const visibleChoices = useMemo(() => {
    const hidden = hiddenChoiceIds(story, state, encounterOn);
    return (state.choices || []).filter((choice) => !hidden.has(choice.id));
    // `state` is read only through its choices and encounter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [story, encounterOn, state.choices, state.world?.encounter]);
  // Every choice an approach: the row goes, and the approaches take the digits.
  const allMatched = (state.choices || []).length > 0 && visibleChoices.length === 0;
  // ...and when core's own encounter panel draws them, the shelf holds the
  // only moves (T10 fix round 2): the panel comes first in the shelf, and
  // `data-moves="shelf"` gives the shelf the choice row's room (index.css),
  // so the first approach is on screen at rest on a phone too.
  const movesInShelf = allMatched && encounterOn;
  const shelfPanels = useMemo(
    () =>
      movesInShelf
        ? [...regions.shelf.filter((panel) => panel.id === "encounter"), ...regions.shelf.filter((panel) => panel.id !== "encounter")]
        : regions.shelf,
    [movesInShelf, regions]
  );

  // No `onCustom`: a core panel has no route to typed text at all, so rule 1
  // is structural for core (T10 fix round 1).
  const panelProps = {
    state,
    onChoose,
    showDiceBreakdown,
    narrow,
    blocked,
    onOpenSheet: openSheetTo,
    bindDigits: allMatched,
    controlsOff: off,
  };

  function submitCustom(event) {
    event.preventDefault();
    const value = text.trim();
    if (!value || off) return;
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
        chips={<Region panels={regions.header} props={panelProps} />}
      />

      <main className="scene__grid">
        <div className="scene__col scene__col--assistant">
          {Aside && <Aside {...slot} />}
        </div>

        {/* NAMED AREAS, NOT CHILD POSITIONS (spec §3.1, F1). Every area has a
            fixed wrapper in a fixed order; the grid places each by name, so
            what renders inside can no longer move a row. An empty wrapper
            renders no children and costs a zero-height track and no margin. */}
        <section className="scene__col scene__col--main" data-stage={stageOn ? "on" : "off"}
          data-moves={movesInShelf ? "shelf" : undefined}
        >
          <div className="stage-area">
            {Stage && <Stage {...slot} />}
            <Region panels={regions.stage} props={panelProps} />
          </div>

          <BeatFrame world={state.world} />

          <NarrativeLog entries={state.log} busy={state.busy} />

          <div className="think-area">
            {/* The old bare "the world is deciding" indicator is the header of
                the reasoning panel, so the same three dots either sit there
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
          </div>

          {/* The shelf: bounded (--shelf-max) and scrolling inside itself, so
              nothing in it can paint over the choices (spec §3.2). It holds
              the shelf region's panels (core/panels/resolve.js); each renders
              nothing when it has nothing -- the negotiation unless a pipeline
              ran this turn. */}
          <div className="shelf">
            <Region panels={shelfPanels} props={panelProps} />
          </div>

          <div className="choices-area">
            {!allMatched && (
              <ChoiceRow
                choices={visibleChoices}
                busy={off}
                blocked={blocked}
                onChoose={onChoose}
                focusSignal={state.choiceFocus || 0}
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
          </div>

          <form className="compose" onSubmit={submitCustom}>
            <input
              className="compose__input"
              ref={composeRef}
              value={text}
              onChange={(e) => {
                if (!off) setText(e.target.value);
              }}
              // A phone has neither key (F10).
              placeholder={coarse ? "Or say what you do…" : "Or say what you do…  (press / to jump here, Esc for the menu)"}
              // readOnly + aria-disabled, never `disabled`: a disabled field
              // throws its focus to <body> mid-turn (F9). Focus in the box is
              // kept: the choice row never takes it when the turn lands (§8.2).
              readOnly={off}
              aria-disabled={off ? "true" : undefined}
              aria-label="Custom action"
            />
            <MicButton
              sessionId={state.sessionId}
              disabled={off || !state.sessionId}
              onTranscript={acceptTranscript}
            />
            <button type="submit" className="btn" disabled={off || !text.trim()}>
              Send
            </button>
          </form>

          {/* The toast region (the roll card): LAST in the DOM so its presence
              moves no other area's margin, and laid over the stage and log
              rows only (index.css, .toast-area), so it can never sit on the
              choices or the compose box (T9 review finding 1). */}
          <div className="toast-area">
            <Region panels={regions.toast} props={panelProps} />
          </div>
        </section>

        <div className="scene__col scene__col--sheet">
          <Ledger {...slot} />
          {/* The ledger region: reference panels under the sheet (the casing
              board by default). Empty, the wrapper is not drawn. */}
          <div className="ledger-panels">
            <Region panels={regions.ledger} props={panelProps} />
          </div>
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
        link={state.link}
        error={state.error}
        // A stale choice (store `errorFinal`) would be refused again: no Try again.
        onRetry={state.errorFinal ? undefined : onRetry}
        canRetry={!off}
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

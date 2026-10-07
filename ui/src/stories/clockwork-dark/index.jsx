/**
 * The Clockwork Dark — story plugin.
 *
 * This file IS the seam. Everything below used to be spelled directly into
 * core: the evil phase lived in the shared reducer, the gear was drawn by the
 * shared header, four overlay keys were hardcoded in the shared keyboard map,
 * and the shared play screen imported Sheet, DiceToast, EncounterPanel and
 * AssistantColumn by name. Moving the flagship out is the only proof the seam
 * is real, so it is moved rather than declared.
 *
 * Slug must match the server's: `games/clockwork-dark/game.yaml`.
 * See core/story.js for what every field means.
 */
import React from "react";

import { matchApproaches, matchedChoiceIds } from "@core/panels/approaches.js";

import AssistantColumn from "./parts/AssistantColumn.jsx";
import DiceToast from "./parts/DiceToast.jsx";
import EncounterPanel from "./parts/EncounterPanel.jsx";
import Inventory from "./parts/Inventory.jsx";
import SceneVisual from "./parts/SceneVisual.jsx";
import Sheet from "./parts/Sheet.jsx";
import Codex from "./screens/Codex.jsx";
import Journal from "./screens/Journal.jsx";
import Notices from "./screens/Notices.jsx";
import Trade from "./screens/Trade.jsx";
import { ONBOARDING } from "./onboarding.js";
import {
  AtlasIcon,
  BoardIcon,
  GearMark,
  JournalIcon,
  PackIcon,
  PhaseBand,
  PhasePill,
  ScalesIcon,
} from "./parts/Marks.jsx";

/**
 * The story's slice of the store.
 *
 * `phase` retints the whole product and `formHistory` is the only record that
 * the companion ever wore a different face. Both were core fields, which meant
 * every story shipped a four-phase corruption clock and a five-faced companion
 * whether it had one or not.
 */
const initialState = { phase: "dormant", formHistory: [] };

/**
 * Append to the form history only when the form actually changed.
 *
 * The companion wears five faces and swaps between them as its trust and the
 * world's awareness move. Nothing in the client ever recorded that it had, so
 * a player who looked away missed the only tell the design gives them.
 */
function rememberForm(history, presence, world) {
  const form = presence?.form;
  if (!form) return history;
  const last = history[history.length - 1];
  if (last && last.form === form) return history;
  return [
    ...history,
    {
      form,
      day: world?.world_day ?? 0,
      turn: world?.turn_number ?? 0,
      portrait: presence.portrait || "",
    },
  ].slice(-8);
}

/**
 * Derive this story's state from the core state that was just reduced.
 *
 * Returning the SAME slice object when nothing moved is load-bearing: the store
 * uses identity to decide whether to rebuild `state`, and a fresh object per
 * streamed token would re-render the companion column sixty times a second.
 */
function reduce(slice, action, next) {
  if (action.type === "RESET") return initialState;
  if (action.type !== "SOCKET") return slice;

  const phase = next.world?.evil_phase || slice.phase;
  const formHistory = rememberForm(slice.formHistory, next.presence, next.world);
  if (phase === slice.phase && formHistory === slice.formHistory) return slice;
  return { phase, formHistory };
}

// The save browser's line for this story (core prints none of its own since
// v0.21.0 -- it used to print "the pattern is …" on every story's saves, F7).
const PHASE_WORD = { dormant: "quiet", stirring: "stirring", spreading: "spreading", consuming: "consuming" };

const Wordmark = () => (
  <h1 className="start__wordmark">
    The Clockwork <span>Dark</span>
  </h1>
);

const StartIntro = () => (
  <p className="start__intro">
    You wake at the forest's edge with the taste of iron and no clear reason for
    it. Ahead, hearth smoke. Somewhere further in, something is winding itself
    into the bones of the world — and it will keep winding whether you become a
    hero or a baker.
  </p>
);

export default {
  slug: "clockwork-dark",
  title: "The Clockwork Dark",
  documentTitle: "The Clockwork Dark",
  beginLabel: "Step into the clearing",
  asideLabel: "Companion",
  onboardingTitle: "Before you begin",
  onboardingFinishLabel: "Step into the trees",
  saveMeta: (save) => (save.evil_phase ? `the pattern is ${PHASE_WORD[save.evil_phase] || save.evil_phase}` : null),

  // Vite turns this into its own CSS chunk, fetched only when this story is the
  // active one. It loads AFTER core's sheet, so its rules win ties -- which is
  // how a story retints core components without a single !important.
  theme: () => import("./theme/clockwork-dark.css"),

  initialState,
  reduce,

  // `data-phase` on <body> is what makes theme/phases.css work. Core writes the
  // attribute and has no idea what it means.
  bodyData: (state) => ({ phase: state.story.phase || "dormant" }),

  onboarding: ONBOARDING,

  // The gear only turns once the world has started to go wrong -- it is a
  // diegetic tell, not a decoration.
  Mark: ({ state }) => <GearMark discovered={state.story.phase !== "dormant"} />,
  HeaderBadge: ({ state, onOpenMenu }) => (
    <PhasePill phase={state.story.phase} onOpenMenu={onOpenMenu} />
  ),
  MenuBanner: ({ state }) => <PhaseBand phase={state.story.phase} />,

  Wordmark,
  StartIntro,

  Aside: ({ state }) => (
    <AssistantColumn
      assistant={state.assistant}
      presence={state.presence}
      formHistory={state.story.formHistory}
      phase={state.story.phase}
      busy={state.busy}
    />
  ),

  /**
   * The top of the centre column.
   *
   * When `world.encounter` is non-empty the encounter takes the scene still's
   * place. Each approach button presses the narrator's choice that carries its
   * `encounter` intent (see `hideChoices`, which hides exactly those choices).
   */
  Stage: ({ state, onChoose, controlsOff }) => {
    const encounter = state.world?.encounter || {};
    if (Object.keys(encounter).length > 0) {
      const offered = matchApproaches(encounter, state.choices);
      return (
        <EncounterPanel
          encounter={encounter}
          world={state.world}
          phase={state.story.phase}
          sceneImage={state.sceneImage}
          // The link's answer as well as the turn's (spec §6.3, T13): a press
          // while offline would reach nothing.
          busy={controlsOff}
          offered={offered}
          // An approach is pressed as the narrator's intent-bearing choice
          // (spec §2.3, rule 1): the engine runs encounter_approach before
          // narration. One the narrator did not offer is not pressable.
          onTake={(approach) => {
            const choice = offered.get(approach.id);
            if (choice) onChoose(choice);
          }}
        />
      );
    }
    return (
      <SceneVisual world={state.world} imageUrl={state.sceneImage} phase={state.story.phase} />
    );
  },

  Ledger: ({ state, onOpenOverlay }) => (
    <Sheet
      world={state.world}
      sessionId={state.sessionId}
      onOpenPack={() => onOpenOverlay("pack")}
    />
  ),

  Toast: ({ state, showDiceBreakdown }) => (
    <DiceToast dice={state.dice} showBreakdown={showDiceBreakdown} />
  ),

  // Its DiceToast and EncounterPanel draw these two systems (spec §2.3), so
  // core's own rolls and encounter panels stand down.
  ownsPanels: ["rolls", "encounter"],

  // Only the choices its approach buttons press (spec §2.3): any other
  // narrator choice stays, and an encounter whose approaches the narrator did
  // not offer hides nothing, so the player always has a move.
  hideChoices: (state) => matchedChoiceIds(state.world?.encounter, state.choices),

  overlays: [
    { id: "pack", key: "i", label: "The pack", Icon: PackIcon, Component: Inventory },
    { id: "journal", key: "j", label: "Journal", Icon: JournalIcon, Component: Journal },
    { id: "codex", key: "c", label: "Codex", Icon: AtlasIcon, Component: Codex },
    {
      id: "notices",
      key: "n",
      label: "Notice board",
      Icon: BoardIcon,
      Component: Notices,
    },
    {
      id: "trade",
      key: "b",
      label: "Barter",
      Icon: ScalesIcon,
      // Core hands every overlay the same `onAct`; barter calls its own verb.
      Component: ({ sessionId, busy, onAct, onClose }) => (
        <Trade sessionId={sessionId} busy={busy} onStrike={onAct} onClose={onClose} />
      ),
    },
  ],
};

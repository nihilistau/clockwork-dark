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
import PeopleStrip from "@core/panels/PeopleStrip.jsx";
import { useSoundOnChange } from "@core/sound/index.js";

import AssistantColumn from "./parts/AssistantColumn.jsx";
import DiceToast from "./parts/DiceToast.jsx";
import EncounterPanel from "./parts/EncounterPanel.jsx";
import EndingPlate from "./parts/EndingPlate.jsx";
import Inventory from "./parts/Inventory.jsx";
import SceneVisual from "./parts/SceneVisual.jsx";
import Sheet from "./parts/Sheet.jsx";
import Codex from "./screens/Codex.jsx";
import Ends from "./screens/Ends.jsx";
import Journal from "./screens/Journal.jsx";
import Notices from "./screens/Notices.jsx";
import Trade from "./screens/Trade.jsx";
import { ONBOARDING } from "./onboarding.js";
import {
  AtlasIcon,
  BoardIcon,
  DoorIcon,
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

// The pattern only deepens (spec §9.2): the phase's toll sounds on an advance, never on a retreat or a load.
const PHASE_ORDER = ["dormant", "stirring", "spreading", "consuming"];

function PhaseBadge({ state, onOpenMenu }) {
  useSoundOnChange(state.story.phase, "clockwork.phase", {
    when: (a, b) => PHASE_ORDER.indexOf(b) > PHASE_ORDER.indexOf(a),
  });
  return <PhasePill phase={state.story.phase} onOpenMenu={onOpenMenu} />;
}

/**
 * The top of the centre column. The encounter's start sound is heard HERE, not in EncounterPanel: the panel
 * mounts only while an encounter exists, and a hook is silent on its first render (spec §6.3 rule 2), so a cue
 * inside it would never play. The Stage is always mounted.
 */
function FlagshipStage({ state, onChoose, controlsOff, blocked = false }) {
  const encounter = state.world?.encounter || {};
  const live = Object.keys(encounter).length > 0 && !encounter.resolved;
  useSoundOnChange(live, "encounter.start", { when: (a, b) => !a && b });
  if (Object.keys(encounter).length > 0) {
    const offered = matchApproaches(encounter, state.choices);
    // True exactly when `hideChoices` (core's rule, below) hides every choice:
    // only then do the digits belong to the approaches (v0.25.0 §8.2).
    const hidden = matchedChoiceIds(encounter, state.choices);
    // Core's rule (Play.jsx `allMatched`): no choices at all is not an empty row.
    const choices = state.choices || [];
    const choiceRowEmpty = choices.length > 0 && choices.every((c) => hidden.has(c.id));
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
        choiceRowEmpty={choiceRowEmpty}
        // An overlay, the menu or a cutscene is up: the digits stand down.
        blocked={blocked}
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
  return <SceneVisual world={state.world} imageUrl={state.sceneImage} phase={state.story.phase} />;
}

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
  // The story's own sound event (v0.24.0 spec §5.2, §9.2); the palette is games/clockwork-dark/data/sounds/sounds.yaml.
  soundEvents: ["clockwork.phase"],
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
  HeaderBadge: PhaseBadge,
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
  Stage: FlagshipStage,

  // The sheet, then who is here (v0.25.0 §8.5): core's people strip in its
  // ledger shape, drawn by the plugin rather than declared in game.yaml's
  // `ui.panels`, because the declaration rides the catalogue (`/api/games`)
  // and would move the local-mode golden's recording (ruling M8: gate, never
  // re-record). The strip draws nothing when nobody is here.
  Ledger: ({ state, onOpenOverlay }) => (
    <>
      <Sheet
        world={state.world}
        sessionId={state.sessionId}
        onOpenPack={() => onOpenOverlay("pack")}
      />
      <div className="ledger-panels">
        <PeopleStrip state={state} region="ledger" />
      </div>
    </>
  ),

  Toast: ({ state, showDiceBreakdown }) => (
    <DiceToast dice={state.dice} showBreakdown={showDiceBreakdown} />
  ),

  // The ending's gallery plate in place of core's gallery line (v0.25.0 §8.6).
  EndingArt: EndingPlate,

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
    // Only the doors open now (v0.25.0 §8.4); the hiding is cosmetic (Ends.jsx).
    {
      id: "ends",
      key: "e",
      label: "The ways it ends",
      Icon: DoorIcon,
      Component: Ends,
      // The payload carries `endings` only for a story with an endings table.
      when: (state) => Array.isArray(state.world?.endings?.gallery),
    },
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
      // Core hands every overlay the same `onAct`: each barter row presses one
      // `buy` or `sell` intent through it (v0.25.0 §7.3).
      Component: ({ state, sessionId, busy, onAct, onClose }) => (
        <Trade state={state} sessionId={sessionId} busy={busy} onAct={onAct} onClose={onClose} />
      ),
    },
  ],
};

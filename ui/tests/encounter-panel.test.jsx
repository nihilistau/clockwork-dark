// @vitest-environment jsdom
/**
 * Encounter approaches are pressed as the narrator's intent-bearing choice
 * (v0.21.0, spec §2.3, §4.5, Review 1 -- rule 1).
 *
 * The client cannot author an intent: `player_choice` carries a choice id,
 * and the server resolves the intent from the options it showed. Typed text
 * resolves to NONE. So an approach button presses the choice whose intent is
 * `{action: "encounter", target: approach.id}`; an approach the narrator did
 * not offer is drawn and not pressable; only matched choices are hidden.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/core/parts/MicButton.jsx", () => ({ default: () => null }));

import Play from "../src/core/screens/Play.jsx";
import EncounterPanel from "../src/core/panels/EncounterPanel.jsx";
import { matchApproaches, matchedChoiceIds } from "../src/core/panels/approaches.js";
import { resolvePanels } from "../src/core/panels/resolve.js";
import { initialState } from "../src/core/store.js";
import flagship from "../src/stories/clockwork-dark/index.jsx";
import neon from "../src/stories/neon-city/index.jsx";
import NeonStage from "../src/stories/neon-city/parts/Stage.jsx";

const ENCOUNTER = {
  id: "watch_stop", round: 0, max_rounds: 3, resolved: false, outcome: "",
  intro: "A lamp on a pole swings round and stops on your face.",
  threat: { name: "A Lantern of the Watch", resolve: 3, resolve_max: 3 },
  approaches: [
    { id: "run", text: "Bolt into the crowd", skill: "stealth", difficulty: "easy", auto: false, cost_gold: 0 },
    { id: "talk", text: "Explain, reasonably", skill: "persuasion", difficulty: "hard", auto: false, cost_gold: 0 },
    { id: "surrender", text: "Go quietly", skill: "", difficulty: "", auto: true, cost_gold: 0 },
  ],
};
const RUN = { id: "a", text: "Bolt for it", intent: { action: "encounter", target: "run" } };
const SURRENDER = { id: "b", text: "Go quietly", intent: { action: "encounter", target: "surrender" } };
const LOOK = { id: "c", text: "Look around" };
const NO_INTENT = { id: "d", text: "Explain, reasonably" };
// Another verb aimed at an approach's id: never an approach.
const TRAVEL_RUN = { id: "e", text: "Run to the docks", intent: { action: "travel", target: "run" } };

let host;
let root;
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  globalThis.fetch = vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) }));
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  React.act(() => root.unmount());
  host.remove();
});

const state = (choices, encounter = ENCOUNTER) => ({
  ...initialState, screen: "scene", sessionId: "s1", link: "live",
  world: { location_id: "tallow_docks", encounter }, choices, story: { phase: "dormant" },
  log: [{ id: "e1", kind: "narration", text: "Stop." }],
});

function render(element) {
  React.act(() => root.render(element));
}

const buttonFor = (text) => [...host.querySelectorAll("button")].find((b) => b.textContent.includes(text));

describe("matchApproaches", () => {
  it("pairs each approach with the choice whose intent targets it", () => {
    const matched = matchApproaches(ENCOUNTER, [LOOK, RUN, SURRENDER, NO_INTENT]);
    expect([...matched.keys()]).toEqual(["run", "surrender"]);
    expect(matched.get("run")).toBe(RUN);
  });

  it("ignores a choice with an approach's text and no intent", () => {
    expect(matchApproaches(ENCOUNTER, [NO_INTENT]).size).toBe(0);
  });

  it("ignores another verb aimed at an approach's id", () => {
    expect(matchApproaches(ENCOUNTER, [TRAVEL_RUN]).size).toBe(0);
    expect([...matchedChoiceIds(ENCOUNTER, [TRAVEL_RUN, RUN])]).toEqual(["a"]);
  });

  it("ignores an encounter intent at no listed approach, and a resolved encounter", () => {
    expect(matchApproaches(ENCOUNTER, [{ id: "x", intent: { action: "encounter", target: "fly" } }]).size).toBe(0);
    expect(matchApproaches({ ...ENCOUNTER, resolved: true }, [RUN]).size).toBe(0);
    expect(matchApproaches({}, [RUN]).size).toBe(0);
  });

  it("first matching choice wins", () => {
    const again = { id: "z", text: "Run again", intent: { action: "encounter", target: "run" } };
    expect(matchApproaches(ENCOUNTER, [RUN, again]).get("run")).toBe(RUN);
  });

  it("matchedChoiceIds is the matched choices' ids", () => {
    expect([...matchedChoiceIds(ENCOUNTER, [RUN, LOOK])]).toEqual(["a"]);
  });
});

describe("the core encounter panel", () => {
  it("presses the intent-bearing choice and never sends typed text", () => {
    const onChoose = vi.fn();
    const onCustom = vi.fn();
    render(<EncounterPanel state={state([RUN, LOOK])} onChoose={onChoose} onCustom={onCustom} />);
    React.act(() => buttonFor("Bolt into the crowd").click());
    expect(onChoose).toHaveBeenCalledWith(RUN);
    expect(onCustom).toHaveBeenCalledTimes(0);
  });

  it("draws an unmatched approach as not pressable, saying so", () => {
    const onChoose = vi.fn();
    render(<EncounterPanel state={state([RUN])} onChoose={onChoose} onCustom={vi.fn()} />);
    const talk = buttonFor("Explain, reasonably");
    expect(talk.getAttribute("aria-disabled")).toBe("true");
    expect(talk.textContent).toContain("not offered this turn");
    React.act(() => talk.click());
    expect(onChoose).not.toHaveBeenCalled();
  });

  it("presses nothing while a turn is running", () => {
    const onChoose = vi.fn();
    render(<EncounterPanel state={{ ...state([RUN]), busy: true }} onChoose={onChoose} />);
    React.act(() => buttonFor("Bolt into the crowd").click());
    expect(onChoose).not.toHaveBeenCalled();
  });

  it("says the terms: threat, resolve, the round (0-based on the wire), the intro on the first round", () => {
    render(<EncounterPanel state={state([RUN])} onChoose={vi.fn()} />);
    expect(host.querySelector("h2").textContent).toContain("A Lantern of the Watch");
    expect(host.textContent).toContain("resolve 3 of 3");
    expect(host.textContent).toContain("round 1 of 3");
    expect(host.textContent).toContain("A lamp on a pole");
    expect(buttonFor("Go quietly").textContent).toContain("no roll");
    expect(host.querySelector('[role="group"]').getAttribute("aria-label")).toBe("Approaches");
  });

  it("folds on a narrow screen while the choice row holds the digits", () => {
    render(<EncounterPanel state={state([RUN, LOOK])} onChoose={vi.fn()} narrow />);
    const toggle = host.querySelector(".panel__toggle");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(host.querySelector(".panel__body").hidden).toBe(true);
  });

  it("never folds when it holds the only moves (plan decision 11), and numbers its keys", () => {
    render(<EncounterPanel state={state([RUN, SURRENDER])} onChoose={vi.fn()} narrow bindDigits />);
    expect(host.querySelector(".panel__toggle")).toBeNull();
    expect(host.querySelector(".panel__body").hidden).toBe(false);
    // Counted over the pressable approaches: "talk" (unmatched) has no key.
    expect(buttonFor("Bolt into the crowd").getAttribute("aria-keyshortcuts")).toBe("1");
    expect(buttonFor("Explain, reasonably").getAttribute("aria-keyshortcuts")).toBeNull();
    expect(buttonFor("Go quietly").getAttribute("aria-keyshortcuts")).toBe("2");
    expect(buttonFor("Go quietly").querySelector(".encpanel__key").textContent).toBe("2");
  });

  it("wears no key numbers while the choice row holds the digits", () => {
    render(<EncounterPanel state={state([RUN, LOOK])} onChoose={vi.fn()} />);
    expect(host.querySelector(".encpanel__key")).toBeNull();
    expect(buttonFor("Bolt into the crowd").getAttribute("aria-keyshortcuts")).toBeNull();
  });

  it("renders nothing once the encounter is resolved", () => {
    render(<EncounterPanel state={state([RUN], { ...ENCOUNTER, resolved: true, outcome: "fled" })} onChoose={vi.fn()} />);
    expect(host.innerHTML).toBe("");
  });

  it("is never drawn twice: a plugin that owns it suppresses core's", () => {
    expect(resolvePanels({ ownsPanels: ["encounter"], panelDeclaration: ["encounter"] }).shelf).toEqual([]);
  });
});

describe("on the play screen", () => {
  const noop = () => {};
  const play = (s, onChoose = noop, onCustom = noop) =>
    render(
      <Play state={s} story={{ slug: "probe", title: "P", overlays: [], onboarding: [], panelDeclaration: ["encounter"] }}
        onChoose={onChoose} onCustom={onCustom} onRetry={noop} onOpenSaves={noop} onOpenSettings={noop}
        onOpenOverlay={noop} onOpenMenu={noop} onToggleReasoning={noop} composeRef={{ current: null }} />
    );

  it("hides exactly the matched choices", () => {
    play(state([RUN, LOOK, TRAVEL_RUN]));
    const chips = [...host.querySelectorAll(".choices .chip")].map((c) => c.textContent);
    expect(chips).toHaveLength(2);
    expect(chips[0]).toContain("Look around");
    expect(chips[1]).toContain("Run to the docks");
    expect(host.querySelector(".scene__col--main").dataset.moves).toBeUndefined();
  });

  it("hides nothing when nothing matched, and nothing for a resolved encounter", () => {
    play(state([LOOK, NO_INTENT]));
    expect(host.querySelectorAll(".choices .chip")).toHaveLength(2);
    play(state([RUN, LOOK], { ...ENCOUNTER, resolved: true }));
    expect(host.querySelectorAll(".choices .chip")).toHaveLength(2);
  });

  it("when every choice matched, the approaches take the digits", () => {
    const onChoose = vi.fn();
    play(state([RUN, SURRENDER]), onChoose);
    expect(host.querySelector(".choices")).toBeNull();
    // The shelf holds the only moves (T10 fix round 2): marked for the CSS
    // that gives it the row's room, the encounter panel first in it.
    expect(host.querySelector(".scene__col--main").dataset.moves).toBe("shelf");
    expect(host.querySelector(".shelf > section").classList.contains("encpanel")).toBe(true);
    React.act(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "2" })));
    expect(onChoose).toHaveBeenCalledWith(SURRENDER);
  });

  it("while visible choices remain, the digits stay with the choice row", () => {
    const onChoose = vi.fn();
    play(state([RUN, LOOK]), onChoose);
    React.act(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "1" })));
    expect(onChoose).toHaveBeenCalledTimes(1);
    expect(onChoose).toHaveBeenCalledWith(LOOK);
  });
});

describe("the flagship's and NEON CITY's own approach buttons", () => {
  it("the flagship presses the matched choice, never typed text, and hides only matched choices", () => {
    const onChoose = vi.fn();
    const onCustom = vi.fn();
    const Stage = flagship.Stage;
    render(<Stage state={state([RUN, LOOK])} busy={false} onChoose={onChoose} onCustom={onCustom} />);
    React.act(() => buttonFor("Bolt into the crowd").click());
    expect(onChoose).toHaveBeenCalledWith(RUN);
    expect(onCustom).not.toHaveBeenCalled();
    const talk = buttonFor("Explain, reasonably");
    expect(talk.getAttribute("aria-disabled")).toBe("true");
    expect(talk.textContent).toContain("not offered this turn");
    React.act(() => talk.click());
    expect(onChoose).toHaveBeenCalledTimes(1);
    expect([...flagship.hideChoices(state([RUN, LOOK]))]).toEqual(["a"]);
  });

  it("NEON CITY presses the matched choice, never typed text, and hides only matched choices", () => {
    const onChoose = vi.fn();
    const onCustom = vi.fn();
    render(<NeonStage state={state([SURRENDER])} busy={false} onChoose={onChoose} onCustom={onCustom} />);
    React.act(() => buttonFor("Go quietly").click());
    expect(onChoose).toHaveBeenCalledWith(SURRENDER);
    const run = buttonFor("Bolt into the crowd");
    expect(run.textContent).toContain("not offered this turn");
    React.act(() => run.click());
    expect(onChoose).toHaveBeenCalledTimes(1);
    expect(onCustom).not.toHaveBeenCalled();
    expect([...neon.hideChoices(state([SURRENDER, LOOK]))]).toEqual(["b"]);
  });

  // v0.21.0 T13 (spec §6.3, §8.2): the plugins' approaches read the slot's
  // `controlsOff`, the one answer to "would a press reach the server", and
  // are aria-disabled rather than `disabled`, so a focused one keeps focus.
  it.each([
    ["the flagship", () => flagship.Stage, () => state([RUN, LOOK]), "Bolt into the crowd"],
    ["NEON CITY", () => NeonStage, () => state([SURRENDER]), "Go quietly"],
  ])("%s's offered approach is aria-disabled and inert while controls are off", (_, stage, at, label) => {
    const onChoose = vi.fn();
    const Stage = stage();
    render(<Stage state={at()} busy={false} controlsOff onChoose={onChoose} />);
    const button = buttonFor(label);
    expect(button.disabled).toBe(false);
    expect(button.getAttribute("aria-disabled")).toBe("true");
    button.focus();
    React.act(() => button.click());
    expect(onChoose).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(button);
  });
});

// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { CATALOG, gesture, installFakeAudio } from "./helpers/fake-audio.js";
import { mount } from "./helpers/dom.js";
import { installCatalog, resetSound, setLevels, soundLog, turnSent, turnSettled, useSoundOnChange } from "../src/core/sound/index.js";
import { narrationVolume, useLinkSounds, useTurnSounds } from "../src/core/sound/hooks.js";
import RollCard from "../src/core/panels/RollCard.jsx";

const PREFS = { muted: false, soundMaster: 1, soundUi: 1, soundGame: 1, soundAlert: 1, soundPhone: 1, soundWorld: 1 };
const CAT = {
  ...CATALOG,
  limits: { ...CATALOG.limits, throttle_ms: 0 },
  events: [...CATALOG.events, "panel.wanted", "link.lost", "link.back", "game.ending"],
  bind: { ...CATALOG.bind, "panel.wanted": "alert.error", "roll.cast": "game.turn", "link.lost": "alert.error",
          "link.back": "alert.error", "game.ending": "game.turn" },
};

let view;
beforeEach(() => { installFakeAudio(); resetSound({ logPlays: true }); installCatalog(CAT); gesture(); setLevels(PREFS); view = mount(); });
afterEach(() => { view.unmount(); resetSound(); });

const plays = (event) => soundLog().filter((r) => r.event === event && !r.dropped).length;

function Poster({ level }) {
  useSoundOnChange(level, "panel.wanted", { when: (a, b) => b > a });
  return null;
}
/** App's shape: the parent settles the turn, its child draws the result. */
function Shell({ busy, level = 0, turns = 0, error = "", phoneUp = false, link = "live" }) {
  useTurnSounds({ busy, error, phoneUp, link, turns });
  return <Poster level={level} />;
}
/** App's own ending cue: declared BEFORE useTurnSounds in App, so it runs first too. */
function EndingShell({ busy, ending, turns }) {
  useSoundOnChange(ending, "game.ending", { when: (a, b) => !a && Boolean(b) });
  useTurnSounds({ busy, error: "", phoneUp: false, link: "live", turns });
  return null;
}
function Link({ link }) { useLinkSounds(link); return null; }

describe("the turn ledger", () => {
  it("settles once per sent turn, never for a replayed one, and marks a new run's", () => {
    expect(turnSettled()).toBe(false);
    turnSent();
    expect(turnSettled()).toEqual({ begin: false });
    expect(turnSettled()).toBe(false);
    turnSent({ begin: true });
    expect(turnSettled()).toEqual({ begin: true });
  });
});

describe("rule 2, in the app's order (F1)", () => {
  it("a rise arriving WITH busy:false in one commit plays; hydration and a fall do not", () => {
    view.render(<Shell busy={false} level={3} />);
    turnSent();
    view.render(<Shell busy={true} level={3} />);
    view.render(<Shell busy={false} level={4} turns={1} />);
    expect(plays("panel.wanted")).toBe(1);
    expect(plays("turn.arrive")).toBe(1);
    view.render(<Shell busy={false} level={6} turns={1} />);
    expect(plays("panel.wanted")).toBe(1);
    expect(soundLog().at(-1).dropped).toBe("not_my_turn");
    turnSent();
    view.render(<Shell busy={true} level={6} turns={1} />);
    view.render(<Shell busy={false} level={2} turns={2} />);
    expect(plays("panel.wanted")).toBe(1);
  });

  it("the ending sounds when it arrives in a sent turn, not when a finished run loads", () => {
    view.render(<EndingShell busy={false} ending="e1" turns={0} />);
    expect(plays("game.ending")).toBe(0);
    view.unmount(); view = mount();
    view.render(<EndingShell busy={false} ending={null} turns={0} />);
    turnSent();
    view.render(<EndingShell busy={true} ending={null} turns={0} />);
    view.render(<EndingShell busy={false} ending="e2" turns={1} />);
    expect(plays("game.ending")).toBe(1);
  });
});

describe("turn.arrive needs a turn payload and a live link (F11)", () => {
  it("a socket drop settles silently; a non-live link is silent; a new run's opening is silent", () => {
    view.render(<Shell busy={false} />);
    turnSent();
    view.render(<Shell busy={true} turns={0} />);
    view.render(<Shell busy={false} turns={0} />);
    turnSent();
    view.render(<Shell busy={true} turns={0} />);
    view.render(<Shell busy={false} turns={1} link="retrying" />);
    turnSent({ begin: true });
    view.render(<Shell busy={true} turns={1} />);
    view.render(<Shell busy={false} turns={2} />);
    expect(plays("turn.arrive")).toBe(0);
  });

  it("an error ending a sent turn is alert.error; a phone_up refusal is silent", () => {
    view.render(<Shell busy={false} />);
    turnSent();
    view.render(<Shell busy={true} />); view.render(<Shell busy={false} error="It failed." />);
    turnSent();
    view.render(<Shell busy={true} />); view.render(<Shell busy={false} error="Put the phone down first." phoneUp />);
    expect(plays("alert.error")).toBe(1);
    expect(plays("turn.arrive")).toBe(0);
  });
});

describe("the roll and the link", () => {
  it("a roll inside a sent turn casts, then lands on its degree; outside one, nothing", () => {
    view.render(<RollCard state={{ dice: { degree: "success", at: 1, total: 14, dc: 12 } }} />);
    expect(plays("roll.cast")).toBe(0);
    turnSent();
    view.render(<RollCard state={{ dice: { degree: "success", at: 2, total: 14, dc: 12 } }} />);
    expect(plays("roll.cast")).toBe(1);
    expect(soundLog().some((r) => r.event === "roll.success")).toBe(true);
  });

  it("link.lost and link.back after the first live; never on the first connect", () => {
    view.render(<Link link="connecting" />);
    view.render(<Link link="live" />);
    expect(plays("link.lost") + plays("link.back")).toBe(0);
    view.render(<Link link="retrying" />);
    view.render(<Link link="live" />);
    expect(soundLog().filter((r) => !r.dropped && r.event.startsWith("link.")).map((r) => r.event)).toEqual(["link.lost", "link.back"]);
  });

  it("mute silences narration too (spec §7; F21)", () => {
    expect(narrationVolume({ muted: true, soundMaster: 1, volume: 1 })).toBe(0);
    expect(narrationVolume({ muted: false, soundMaster: 0.5, volume: 0.8 })).toBeCloseTo(0.4);
  });
});

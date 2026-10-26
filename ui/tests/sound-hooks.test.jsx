// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CATALOG, gesture, installFakeAudio } from "./helpers/fake-audio.js";
import {
  installCatalog, installClickSounds, playSound, resetSound, setLevels, soundLog, turnSent, turnSettled, useRollSounds, useSoundLevels, useSoundOnChange,
} from "../src/core/sound/index.js";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const PREFS = { muted: false, soundMaster: 1, soundUi: 1, soundGame: 1, soundAlert: 1, soundPhone: 1, soundWorld: 1, quietInterface: false };
const CAT = { ...CATALOG, limits: { ...CATALOG.limits, throttle_ms: 0 } };
let host; let root; let off;
const played = () => soundLog().filter((r) => !r.dropped).map((r) => r.event);

beforeEach(() => {
  vi.useFakeTimers();
  installFakeAudio(); resetSound({ logPlays: true }); installCatalog(CAT);
  gesture(); setLevels(PREFS);
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
});
afterEach(() => { if (off) off(); off = null; act(() => root.unmount()); host.remove(); vi.useRealTimers(); resetSound(); });

const click = (el) => act(() => { el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })); });

describe("installClickSounds", () => {
  it("a handler that plays a sound gives exactly one sound", () => {
    off = installClickSounds(document);
    act(() => root.render(<button id="b" onClick={() => playSound("alert.error")}>go</button>));
    click(host.querySelector("#b"));
    act(() => { vi.runAllTimers(); });
    expect(played()).toEqual(["alert.error"]);
  });

  it("a handler whose own sound is dropped still owns the click: no ui.press (re-review R1)", () => {
    off = installClickSounds(document);
    act(() => root.render(<button id="b" onClick={() => playSound("alert.error", { key: "once" })}>go</button>));
    click(host.querySelector("#b"));
    act(() => { vi.runAllTimers(); });
    click(host.querySelector("#b"));               // its sound is dropped as seen the second time
    act(() => { vi.runAllTimers(); });
    expect(played()).toEqual(["alert.error"]);
  });

  it("a plain button gives ui.press", () => {
    off = installClickSounds(document);
    act(() => root.render(<button id="b">go</button>));
    click(host.querySelector("#b"));
    act(() => { vi.runAllTimers(); });
    expect(played()).toEqual(["ui.press"]);
  });
});

describe("useSoundOnChange", () => {
  function Probe({ v }) { useSoundOnChange(v, "turn.arrive"); return null; }
  it("is silent on the first render, plays a change in a sent turn, and is silent on resume", () => {
    act(() => root.render(<Probe v={1} />));
    expect(played()).toEqual([]);
    turnSent();
    act(() => root.render(<Probe v={2} />));
    expect(played()).toEqual(["turn.arrive"]);
    turnSettled();
    act(() => root.render(<Probe v={3} />));                       // a change with no sent turn: a resume or rejoin
    expect(played()).toEqual(["turn.arrive"]);
    expect(soundLog().at(-1).dropped).toBe("not_my_turn");
  });
});

describe("installClickSounds: data-sound and checkboxes", () => {
  it("a named data-sound on the control or an ancestor plays that event; a checkbox toggles", () => {
    installCatalog({ ...CAT, events: [...CAT.events, "ui.toggle"], bind: { ...CAT.bind, "ui.toggle": "ui.click" } });
    off = installClickSounds(document);
    act(() => root.render(<div data-sound="alert.error"><button id="b">go</button><input id="c" type="checkbox" /></div>));
    click(host.querySelector("#b"));
    act(() => { vi.runAllTimers(); });
    expect(played()).toEqual(["alert.error"]);
    act(() => root.render(<input id="c" type="checkbox" />));
    click(host.querySelector("#c"));
    act(() => { vi.runAllTimers(); });
    expect(played().at(-1)).toBe("ui.toggle");
  });

  it("data-sound none, a disabled button and an aria-disabled one are silent", () => {
    off = installClickSounds(document);
    act(() => root.render(<div><button id="a" data-sound="none">a</button><button id="b" disabled>b</button><button id="c" aria-disabled="true">c</button></div>));
    for (const id of ["#a", "#b", "#c"]) click(host.querySelector(id));
    act(() => { vi.runAllTimers(); });
    expect(played()).toEqual([]);
  });
});

describe("useRollSounds", () => {
  function Roll({ dice }) { useRollSounds(dice); return null; }
  it("casts then lands once per roll inside a sent turn; a re-render of the same roll and a roll outside a turn are silent", () => {
    act(() => root.render(<Roll dice={{ at: 1, degree: "success" }} />));
    expect(played()).toEqual([]);
    turnSent();
    act(() => root.render(<Roll dice={{ at: 2, degree: "success" }} />));
    act(() => { vi.runAllTimers(); });
    act(() => root.render(<Roll dice={{ at: 2, degree: "success" }} />));
    expect(soundLog().filter((r) => r.event === "roll.cast").length).toBe(1);
    expect(played()).toContain("roll.success");
    expect(played().filter((e) => e === "roll.success").length).toBe(1);
  });
});

describe("useSoundLevels", () => {
  function Levels({ prefs }) { useSoundLevels(prefs); return null; }
  it("keeps the buses on the preferences: mute silences, unmute plays again", () => {
    act(() => root.render(<Levels prefs={{ ...PREFS, muted: true }} />));
    playSound("alert.error");
    expect(soundLog().at(-1).dropped).toBe("muted");
    act(() => root.render(<Levels prefs={PREFS} />));
    playSound("alert.error");
    expect(soundLog().at(-1).dropped).toBeUndefined();
  });
});

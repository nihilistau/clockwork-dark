// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CATALOG, gesture, installFakeAudio } from "./helpers/fake-audio.js";
import {
  installCatalog, installClickSounds, playSound, resetSound, setLevels, soundLog, turnSent, turnSettled, useSoundOnChange,
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

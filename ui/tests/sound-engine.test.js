// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CATALOG, gesture, installFakeAudio } from "./helpers/fake-audio.js";
import { installCatalog, playCount, playSound, resetSound, setLevels, soundLog } from "../src/core/sound/index.js";

let log;
beforeEach(() => { log = installFakeAudio(); resetSound({ logPlays: true }); installCatalog(CATALOG); });
afterEach(() => resetSound());

const PREFS = { muted: false, soundMaster: 1, soundUi: 1, soundGame: 1, soundAlert: 1, soundPhone: 1, soundWorld: 1, quietInterface: false };

describe("the sound engine", () => {
  it("a suspended context still schedules: it resumes and plays (F33)", () => {
    gesture(); setLevels(PREFS);
    log.contexts[0].state = "suspended";
    const resumes = log.resumes;
    playSound("ui.press");
    expect(log.resumes).toBe(resumes + 1);
    expect(soundLog().at(-1).dropped).toBeUndefined();
  });

  it("makes no context before a gesture, and drops (never queues) a play", () => {
    playSound("ui.press");
    expect(log.contexts.length).toBe(0);
    gesture();
    expect(log.contexts.length).toBe(1);
    expect(log.starts.length).toBe(0);                        // the dropped play did not come back
    expect(soundLog().at(-1).dropped).toBe("locked");
  });

  it("creates and resumes on the first gesture, and resumes a suspended context on a later one", () => {
    gesture("touchend");
    expect(log.resumes).toBe(1);
    log.contexts[0].state = "suspended";
    gesture("click");
    expect(log.resumes).toBe(2);
    gesture("keydown");
    expect(log.resumes).toBe(2);                              // running: no resume
  });

  it("plays through master x category, and mute or a zero category plays nothing", () => {
    gesture(); setLevels({ ...PREFS, soundMaster: 0.5, soundUi: 0.25 });
    const ctx = log.contexts[0];
    const gainOf = (n) => n.gain.value;
    const gains = log.nodes.filter((n) => n.kind === "gain" && n.to);
    const master = gains.find((n) => n.to === ctx.destination);
    expect(gainOf(master)).toBe(0.5);
    expect(master.gain.value).toBe(0.5);
    const ui = gains.find((n) => n.to === master && gainOf(n) === 0.25);
    expect(ui).toBeTruthy();
    playSound("ui.press");
    expect(log.starts.length).toBeGreaterThan(0);
    const before = log.starts.length;
    setLevels({ ...PREFS, muted: true });
    expect(gainOf(master)).toBe(0);
    playSound("turn.arrive");
    expect(log.starts.length).toBe(before);
    setLevels({ ...PREFS, soundGame: 0 });
    playSound("turn.arrive");
    expect(log.starts.length).toBe(before);
    expect(soundLog().at(-1).dropped).toBe("muted");
  });

  it("quiet interface plays only essential sounds", () => {
    gesture(); setLevels({ ...PREFS, quietInterface: true });
    playSound("ui.press");
    expect(soundLog().at(-1).dropped).toBe("quiet");
    playSound("alert.error");
    expect(soundLog().at(-1).dropped).toBeUndefined();
  });

  it("throttles a sound inside its throttle_ms", () => {
    gesture(); setLevels(PREFS);
    const clock = vi.spyOn(performance, "now");
    clock.mockReturnValue(1000);
    playSound("ui.press");
    clock.mockReturnValue(1030);
    playSound("ui.press");
    expect(soundLog().at(-1).dropped).toBe("throttled");
    clock.mockReturnValue(1100);
    playSound("ui.press");
    expect(soundLog().at(-1).dropped).toBeUndefined();
    clock.mockRestore();
  });

  it("the voice cap counts only voices still sounding", () => {
    gesture(); setLevels(PREFS);
    installCatalog({ ...CATALOG, limits: { ...CATALOG.limits, voices: 2, throttle_ms: 0 } });
    const ctx = log.contexts[0];
    for (let i = 0; i < 4; i += 1) { playSound("ui.press"); ctx.currentTime += 1; }   // each is long over before the next
    expect(soundLog().filter((r) => r.stopped).length).toBe(0);
  });

  it("a malformed row never throws out of play, and is not counted", () => {
    gesture(); setLevels(PREFS);
    const bad = { ...CATALOG, sounds: { ...CATALOG.sounds, "ui.click": { category: "ui", synth: { sequence: { voice: { wave: "sine" }, notes: [[0, "H9", 100]] } } } } };
    installCatalog(bad);
    const n = playCount();
    expect(() => playSound("ui.press")).not.toThrow();
    expect(soundLog().at(-1).dropped).toBe("error");
    expect(playCount()).toBe(n);
  });

  it("resetting the engine closes the previous context", () => {
    gesture();
    resetSound();
    expect(log.closed).toBe(1);
  });

  it("caps the voices and stops the oldest", () => {
    gesture(); setLevels(PREFS);
    installCatalog({ ...CATALOG, limits: { ...CATALOG.limits, voices: 2, throttle_ms: 0 } });
    for (const e of ["ui.press", "turn.arrive", "alert.error"]) playSound(e);
    expect(soundLog().filter((r) => r.stopped).length).toBe(1);
  });

  it("an unbound event is silent, and unknown is silent unless the catalogue is strict", () => {
    gesture(); setLevels(PREFS);
    playSound("roll.cast");
    expect(soundLog().at(-1).dropped).toBe("unbound");
    expect(() => playSound("made.up")).not.toThrow();
    installCatalog(CATALOG, { strict: true });
    expect(() => playSound("made.up")).toThrow(/made\.up/);
  });
});

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { CATALOG, gesture, installFakeAudio } from "./helpers/fake-audio.js";
import { installCatalog, markSeen, playSound, resetSound, setLevels, soundLog } from "../src/core/sound/index.js";

const PREFS = { muted: false, soundMaster: 1, soundUi: 1, soundGame: 1, soundAlert: 1, soundPhone: 1, soundWorld: 1 };
beforeEach(() => {
  installFakeAudio(); resetSound({ logPlays: true });
  installCatalog({ ...CATALOG, limits: { ...CATALOG.limits, throttle_ms: 0 } });
  gesture(); setLevels(PREFS);
});
afterEach(() => resetSound());

const played = () => soundLog().filter((r) => !r.dropped).length;

describe("keys", () => {
  it("a key plays once", () => {
    playSound("alert.error", { key: "m1" }); playSound("alert.error", { key: "m1" });
    expect(played()).toBe(1);
    expect(soundLog().at(-1).dropped).toBe("seen");
  });

  it("markSeen keys never play, and log nothing themselves", () => {
    const before = soundLog().length;
    markSeen(["m2", "m3"]);
    expect(soundLog().length).toBe(before);
    playSound("alert.error", { key: "m2" });
    expect(played()).toBe(0);
  });

  it("keeps only the 512 newest keys", () => {
    markSeen(Array.from({ length: 513 }, (_, i) => `k${i}`));
    playSound("alert.error", { key: "k0" });                 // the oldest was dropped: it plays
    playSound("alert.error", { key: "k512" });               // the newest is still seen
    expect(played()).toBe(1);
  });

  it("two keys in one tick both play", () => {
    playSound("alert.error", { key: "a" }); playSound("turn.arrive", { key: "b" });
    expect(played()).toBe(2);
  });
});

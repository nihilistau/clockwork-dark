// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { CATALOG, gesture, installFakeAudio } from "./helpers/fake-audio.js";
import { installCatalog, playSound, resetSound, setLevels, soundLog } from "../src/core/sound/index.js";

const PREFS = { muted: false, soundMaster: 1, soundUi: 1, soundGame: 1, soundAlert: 1, soundPhone: 1, soundWorld: 1 };
const settle = () => new Promise((r) => setTimeout(r, 0));
afterEach(() => resetSound());

describe("file sounds", () => {
  it("fetches nothing before a gesture", () => {
    const log = installFakeAudio(); resetSound(); installCatalog(CATALOG);
    playSound("story.door");
    expect(log.fetches).toEqual([]);
  });

  it("plays the fallback and fetches nothing when Ogg cannot play", async () => {
    const log = installFakeAudio({ canPlayOgg: "" }); resetSound({ logPlays: true }); installCatalog(CATALOG);
    gesture(); setLevels(PREFS);
    playSound("story.door");
    await settle();
    expect(log.fetches).toEqual([]);
    expect(soundLog().at(-1).fallback).toBe(true);
    expect(log.nodes.some((n) => n.kind === "buffer")).toBe(true);   // the noise layer's buffer source
  });

  it("a decode failure plays the fallback and warns once per sound", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const log = installFakeAudio({ decodeFails: true }); resetSound({ logPlays: true }); installCatalog({ ...CATALOG, limits: { ...CATALOG.limits, throttle_ms: 0 } });
    gesture(); setLevels(PREFS);
    playSound("story.door"); await settle(); await settle();
    playSound("story.door"); await settle(); await settle();
    expect(log.fetches).toEqual(["/sound/probe/files/door.ogg"]);
    expect(soundLog().filter((r) => r.fallback).length).toBe(2);
    expect(warn).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });
});

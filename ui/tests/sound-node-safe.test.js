import { describe, expect, it } from "vitest";

describe("the sound module in node", () => {
  it("imports with no window and installs nothing", async () => {
    expect(typeof globalThis.window).toBe("undefined");
    const sound = await import("../src/core/sound/index.js");
    expect(typeof sound.playSound).toBe("function");
    expect(() => sound.playSound("ui.press")).not.toThrow();      // no catalogue, no window: silent
  });

  it("the panel registry imports with no side effect: every panel pulls the sound module and nothing listens or loads", async () => {
    const { readFileSync } = await import("node:fs");
    // Prove the case is not vacuous: the panels do import the sound module.
    for (const panel of ["WantedPoster", "JobPanel", "CasingBoard", "EncounterPanel", "RollCard"]) {
      expect(readFileSync(new URL(`../src/core/panels/${panel}.jsx`, import.meta.url), "utf8"), panel).toContain("sound/index.js");
    }
    const registry = await import("../src/core/panels/registry.js");
    expect(registry).toBeTruthy();
    expect(typeof globalThis.window).toBe("undefined");
    expect(typeof globalThis.document).toBe("undefined");
    expect(typeof globalThis.AudioContext).toBe("undefined");   // importing built no audio context
  });
});

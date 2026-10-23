import { describe, expect, it } from "vitest";

describe("the sound module in node", () => {
  it("imports with no window and installs nothing", async () => {
    expect(typeof globalThis.window).toBe("undefined");
    const sound = await import("../src/core/sound/index.js");
    expect(typeof sound.playSound).toBe("function");
    expect(() => sound.playSound("ui.press")).not.toThrow();      // no catalogue, no window: silent
  });

  it("the panel registry still imports (it pulls every core panel, each importing the sound module)", async () => {
    const registry = await import("../src/core/panels/registry.js");
    expect(registry).toBeTruthy();
  });
});

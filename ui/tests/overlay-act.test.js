import { describe, expect, it, vi } from "vitest";
import { routeOverlayAct } from "../src/core/overlayAct.js";

describe("an overlay's act", () => {
  it("sends a string as typed text (NEON CITY's and the Garden's overlays)", () => {
    const sendText = vi.fn();
    const sendIntent = vi.fn();
    routeOverlayAct("I look at the paper", { sendText, sendIntent });
    expect(sendText).toHaveBeenCalledWith("I look at the paper");
    expect(sendIntent).not.toHaveBeenCalled();
  });
  it("sends an intent object as an overlay action", () => {
    const sendText = vi.fn();
    const sendIntent = vi.fn();
    routeOverlayAct({ action: "eat", target: "loaf", label: "Eat: Loaf" }, { sendText, sendIntent });
    expect(sendIntent).toHaveBeenCalledWith({ action: "eat", target: "loaf", label: "Eat: Loaf" });
    expect(sendText).not.toHaveBeenCalled();
  });
  it("drops anything else", () => {
    const sendText = vi.fn();
    const sendIntent = vi.fn();
    routeOverlayAct({ target: "loaf" }, { sendText, sendIntent });
    routeOverlayAct(null, { sendText, sendIntent });
    routeOverlayAct("   ", { sendText, sendIntent });
    expect(sendText).not.toHaveBeenCalled();
    expect(sendIntent).not.toHaveBeenCalled();
  });
});

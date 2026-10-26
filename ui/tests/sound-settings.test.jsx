// @vitest-environment jsdom
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mount } from "./helpers/dom.js";
import Settings, { DEFAULTS, loadPrefs } from "../src/core/screens/Settings.jsx";

afterEach(() => localStorage.clear());

describe("the Sound settings", () => {
  it("adds the sound defaults and keeps an old player's prefs", () => {
    localStorage.setItem("clockwork_prefs", JSON.stringify({ volume: 0.3, muted: true }));
    const prefs = loadPrefs();
    expect(prefs.volume).toBe(0.3);
    expect(prefs.muted).toBe(true);
    expect(prefs.soundMaster).toBe(DEFAULTS.soundMaster);
    expect(DEFAULTS).toMatchObject({ soundMaster: 0.8, soundUi: 0.6, soundGame: 0.8, soundAlert: 0.9, soundPhone: 0.9,
      soundWorld: 0.8, quietInterface: false, soundChoices: {} });
  });

  it("draws the master, five categories, narration, mute and quiet interface, and the audition link", async () => {
    globalThis.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ settings: [], groups: [] }) }));
    const view = mount();
    await view.renderAsync(<Settings prefs={DEFAULTS} onChange={() => {}} onClose={() => {}} />);
    const text = view.host.textContent;
    for (const word of ["Master", "Interface", "Game", "Alerts", "Phone", "World", "Narration", "Mute all sound", "Quiet interface"]) {
      expect(text).toContain(word);
    }
    expect(text).not.toContain("Mute narration audio");
    expect(view.host.querySelector('a[href="/?sounds=1"]')).not.toBeNull();
    view.unmount();
  });
});

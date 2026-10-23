// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CATALOG, gesture, installFakeAudio } from "./helpers/fake-audio.js";
import { click, key, mount, typeInto } from "./helpers/dom.js";
import { resetSound, soundLog } from "../src/core/sound/index.js";
import Audition from "../src/core/sound/Audition.jsx";

const ENGINE_KEY = (id) => `content/sounds/sounds.yaml › sounds › ${id}`;
const PROBE_KEY = (id) => `games/probe/data/sounds/sounds.yaml › sounds › ${id}`;
const engineRows = Object.fromEntries(Object.entries(CATALOG.sounds).filter(([id]) => id !== "story.door")
  .map(([id, row]) => [id, { ...row, scope: "_engine", key: ENGINE_KEY(id), overrides: false }]));
const ENGINE = { ...CATALOG, events: CATALOG.events.filter((e) => e !== "story.door"),
  bind: Object.fromEntries(Object.entries(CATALOG.bind).filter(([e]) => e !== "story.door")), sounds: engineRows };
const STORY = {
  slug: "probe", title: "Probe", declares: true, events: [...CATALOG.events],
  bind: { ...CATALOG.bind },
  sounds: {
    ...engineRows,
    "ui.click": { ...CATALOG.sounds["ui.click"], scope: "probe", key: PROBE_KEY("ui.click"), overrides: true },
    "story.door": { ...CATALOG.sounds["story.door"], scope: "probe", key: PROBE_KEY("story.door"), overrides: false,
      provenance: { author: "Kenney (www.kenney.nl)", pack: "RPG Audio", licence: "CC0-1.0" } },
  },
  overrides: ["ui.click"],
};
const BENCH = { slug: "bench", title: "Bench", declares: false, events: [...ENGINE.events], bind: { ...ENGINE.bind }, sounds: { ...engineRows }, overrides: [] };
const BROKEN = { slug: "broken", title: "Broken", declares: true, error: "games/broken/data/sounds/sounds.yaml: sounds.x: bad" };
const BODY = { engine: ENGINE, stories: [STORY, BENCH, BROKEN] };

const gestureAndSettle = () => React.act(async () => { gesture(); await new Promise((r) => setTimeout(r, 5)); });
const section = (host, scope) => host.querySelector(`section[data-scope="${scope}"]`);
const row = (host, scope, id) => section(host, scope).querySelector(`[data-sound-id="${id}"]`);

let view;
// installFakeAudio replaces fetch with the file fetch; the page's catalogue fetch rides on top of it.
function installAudio(opts) {
  const log = installFakeAudio(opts);
  const files = globalThis.fetch;
  globalThis.fetch = vi.fn(async (url) => (String(url).startsWith("/api/sounds/catalog") ? { ok: true, json: async () => BODY } : files(url)));
  return log;
}

beforeEach(() => { try { localStorage.clear(); } catch { /* none */ } view = mount(); });
afterEach(() => { view.unmount(); resetSound(); });

describe("the audition page", () => {
  it("lists each scope's sounds with their keys, marks overrides, and names a story that declares none", async () => {
    installAudio(); resetSound({ logPlays: true });
    await view.renderAsync(<Audition />);
    expect(section(view.host, "_engine").textContent).toContain("Engine");
    expect(row(view.host, "_engine", "ui.click").textContent).toContain(ENGINE_KEY("ui.click"));
    expect(row(view.host, "probe", "ui.click").textContent).toContain(PROBE_KEY("ui.click"));
    expect(row(view.host, "probe", "ui.click").textContent).toContain("overrides the engine's");
    expect(row(view.host, "probe", "story.door").textContent).toContain("RPG Audio");
    expect(section(view.host, "_engine").querySelector('[data-sound-id="story.door"]')).toBeNull();
    expect(section(view.host, "bench").textContent).toContain("Uses the engine's sounds");
  });

  it("shows a story whose sounds.yaml is broken with its error, and does not crash", async () => {
    installAudio(); resetSound();
    await view.renderAsync(<Audition />);
    expect(section(view.host, "broken").textContent).toContain("sounds.x: bad");
    expect(section(view.host, "broken").querySelector("[data-sound-id]")).toBeNull();
  });

  it("marks a file row 'fallback' once the Ogg probe fails, and not when it succeeds (F9, F29)", async () => {
    installAudio({ canPlayOgg: "" }); resetSound({ logPlays: true });
    await view.renderAsync(<Audition />);
    await gestureAndSettle();
    expect(row(view.host, "probe", "story.door").getAttribute("data-fallback")).toBe("true");
    view.unmount(); view = mount();
    installAudio({ canPlayOgg: "probably" }); resetSound({ logPlays: true });
    await view.renderAsync(<Audition />);
    await gestureAndSettle();
    expect(row(view.host, "probe", "story.door").getAttribute("data-fallback")).not.toBe("true");
  });

  it("plays a row through the engine by its sound id, not dropped", async () => {
    installAudio(); resetSound({ logPlays: true });
    await view.renderAsync(<Audition />);
    await React.act(async () => { gesture(); });
    click(row(view.host, "probe", "ui.click").querySelector("button.audition__play"));
    expect(soundLog().some((r) => r.sound === "ui.click" && !r.dropped)).toBe(true);
  });

  it("filters by id, event, label or category, in every section", async () => {
    installAudio(); resetSound();
    await view.renderAsync(<Audition />);
    typeInto(view.host.querySelector("input.audition__filter"), "door");
    const shown = [...view.host.querySelectorAll("[data-sound-id]")].map((r) => [r.closest("section").getAttribute("data-scope"), r.getAttribute("data-sound-id")]);
    expect(shown).toEqual([["probe", "story.door"]]);
  });

  it("copies a key", async () => {
    installAudio(); resetSound();
    const write = vi.fn(async () => {});
    Object.assign(navigator, { clipboard: { writeText: write } });
    await view.renderAsync(<Audition />);
    click(row(view.host, "probe", "ui.click").querySelector("button.audition__copy"));
    expect(write).toHaveBeenCalledWith(PROBE_KEY("ui.click"));
  });

  it("marks the fallback even when the engine's unlock listener is registered AFTER the page's (not listener order)", async () => {
    installAudio({ canPlayOgg: "" }); resetSound({ logPlays: true });
    await view.renderAsync(<Audition />);
    resetSound({ logPlays: true });       // a fresh engine: its unlock listener now sits behind the page's own
    await gestureAndSettle();
    expect(row(view.host, "probe", "story.door").getAttribute("data-fallback")).toBe("true");
  });

  it("writes clockwork_prefs only when the player changes a level, not on mount", async () => {
    installAudio(); resetSound(); localStorage.clear();
    await view.renderAsync(<Audition />);
    expect(localStorage.getItem("clockwork_prefs")).toBeNull();
    const mute = view.host.querySelector('input[type="checkbox"]');
    click(mute);
    expect(JSON.parse(localStorage.getItem("clockwork_prefs")).muted).toBe(true);
  });

  it("shows the unlock bar until the first gesture", async () => {
    installAudio(); resetSound();
    await view.renderAsync(<Audition />);
    expect(view.host.querySelector(".audition__unlock")).not.toBeNull();
    await gestureAndSettle();
    expect(view.host.querySelector(".audition__unlock")).toBeNull();
  });

  it("'/' focuses the filter, but not while typing in it", async () => {
    installAudio(); resetSound();
    await view.renderAsync(<Audition />);
    const filter = view.host.querySelector("input.audition__filter");
    document.body.appendChild(view.host);
    key("/");
    expect(document.activeElement).toBe(filter);
  });

  it("'Play each' plays every row of its section, one a second, and only that section", async () => {
    vi.useFakeTimers();
    try {
      installAudio(); resetSound({ logPlays: true });
      await view.renderAsync(<Audition />);
      await React.act(async () => { gesture(); await vi.advanceTimersByTimeAsync(5); });
      const ids = Object.keys(STORY.sounds);
      click(section(view.host, "probe").querySelector("button.audition__each"));
      await React.act(async () => { await vi.advanceTimersByTimeAsync(ids.length * 1000); });
      const played = soundLog().filter((r) => !r.dropped).map((r) => r.sound);
      expect(played).toEqual(ids);       // every row of the probe section, in order, none of the others
    } finally { vi.useRealTimers(); }
  });
});

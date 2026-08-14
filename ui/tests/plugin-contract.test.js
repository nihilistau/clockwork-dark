/**
 * @vitest-environment jsdom
 *
 * THE PLUGIN CONTRACT, held against every plugin that ships.
 *
 * This is the test that would have caught a plugin drifting from the seam. The
 * contract in core/story.js is a comment; a comment cannot fail a build, and
 * the client has had exactly this shape of defect before -- a slot documented
 * and never passed (`dispatch`), a component reading five field names the
 * server had never sent, an overlay wired against a payload key that may not
 * exist. Every one of those was invisible until someone played the story.
 *
 * WHAT IS ASSERTED, and why each one is here rather than being obvious:
 *
 *   every exported key is one core reads
 *       A plugin exporting `Sidebar` or `onTurn` is not a bug the browser will
 *       report. It renders nothing, throws nothing, and the author believes the
 *       slot is live. The allowed set below is checked against what core
 *       ACTUALLY reads, so this cannot rot into a stale list.
 *
 *   every slot is the right type
 *       React renders a non-component silently as nothing.
 *
 *   theme() resolves
 *       `loadStory` does `await found.theme()` before first paint, inside a
 *       try/catch that falls back to CORE_ONLY on any throw. A theme whose
 *       import path is wrong therefore costs the story its ENTIRE plugin --
 *       every slot, not just the stylesheet -- and the only symptom is a
 *       console line.
 *
 *   overlays are well formed and their keys are unique
 *       App builds `{key: id}` from the list. Two entries claiming `c` means
 *       one shortcut silently wins and the other is dead.
 *
 *   reduce is stable
 *       Returning a fresh object per action is the documented performance bug:
 *       the store compares slice identity, so an unstable reduce re-renders
 *       every consumer of `state.story` on every streamed token.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

const PLUGINS = import.meta.glob("../src/stories/*/index.jsx");

// Resolved from the cwd (vitest sets it to `ui/`) and NOT from
// `import.meta.url`: this file runs under jsdom, where `import.meta.url` is an
// http:// URL and `fileURLToPath` throws on it.
const CORE = resolve(process.cwd(), "src/core");
// `main.jsx` is core too, and it is the ONLY reader of `documentTitle` -- it
// sets the tab title before mounting. Harvesting core/ alone reported that slot
// as unknown for all three plugins, which is exactly the false negative a
// hand-written allowlist would have hidden and this one surfaced immediately.
const MAIN = resolve(process.cwd(), "src/main.jsx");

/**
 * Slots core reads off the plugin object, harvested from core's own source.
 *
 * Everything reached as `story.X` or `story?.X` in core, plus the four core
 * takes by another route: `slug` and `title` are spread in `loadStory`,
 * `theme` is called there, and `initialState` / `reduce` are read off the
 * plugin by `createStore`. Harvesting rather than hand-listing is the point --
 * a hand-list goes stale the first time a slot is added, and a stale allowlist
 * that still passes is worse than no test.
 */
function slotsCoreReads() {
  const found = new Set(["slug", "title", "theme", "initialState", "reduce"]);
  const scan = (path) => {
    const text = readFileSync(path, "utf8");
    for (const match of text.matchAll(/\bstory\??\.([A-Za-z_]\w*)/g)) {
      found.add(match[1]);
    }
    for (const match of text.matchAll(/\b(?:plugin|found)\??\.([A-Za-z_]\w*)/g)) {
      found.add(match[1]);
    }
  };
  const walk = (dir) => {
    for (const name of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, name.name);
      if (name.isDirectory()) walk(path);
      else if (/\.jsx?$/.test(name.name)) scan(path);
    }
  };
  walk(CORE);
  scan(MAIN);
  // `story.js` is a MODULE PATH, not a slot. It is the one false positive the
  // regex above can produce and it is stable, so it is removed by name rather
  // than by making the pattern cleverer.
  found.delete("js");
  return found;
}

const ALLOWED = slotsCoreReads();

/** The three plugin directories that ship, from the same glob core uses. */
const NAMES = Object.keys(PLUGINS)
  .map((path) => path.replace("../src/stories/", "").replace("/index.jsx", ""))
  .sort();

const isComponent = (value) => typeof value === "function";

describe("the plugin directory", () => {
  it("ships the four story plugins plus the engine's own", () => {
    // Not a count: the names. A plugin appearing with no story pointing at it
    // is a chunk in the committed dist/ that nothing can ever load, and one
    // disappearing is a story that silently falls back to something else.
    //
    // `_engine` is the odd one and belongs here: it is pointed at by every
    // story that declares no `ui.plugin` -- the default rather than a choice --
    // and by `dev-story` explicitly. Underscore-prefixed so it sorts first and
    // so nobody mistakes it for a game; `games/_engine/` does not exist.
    expect(NAMES).toEqual([
      "_engine",
      "clockwork-dark",
      "neon-city",
      "the-long-con",
      "wicked-garden",
    ]);
  });

  it("harvested a plausible slot list from core", () => {
    // A guard on the guard. If the regex above ever matches nothing, every
    // "unknown key" assertion below would pass vacuously against an allowlist
    // of five, which is the failure mode a harvested list has and a hand
    // written one does not.
    expect(ALLOWED.size).toBeGreaterThan(15);
    for (const slot of ["Ledger", "Stage", "overlays", "bodyData", "hideChoices"]) {
      expect(ALLOWED.has(slot)).toBe(true);
    }
  });
});

describe.each(NAMES)("plugin: %s", (name) => {
  const load = PLUGINS[`../src/stories/${name}/index.jsx`];

  it("exports a default object and nothing core cannot read", async () => {
    const plugin = (await load()).default;
    expect(plugin).toBeTypeOf("object");

    const unknown = Object.keys(plugin).filter((key) => !ALLOWED.has(key));
    expect(unknown, `${name} exports keys core never reads`).toEqual([]);
  });

  it("names itself", async () => {
    const plugin = (await load()).default;
    // The plugin's own id. It no longer has to equal the running story's slug
    // -- two stories may share one plugin -- but it must be a non-empty string
    // or `loadStory`'s `found.slug || slug` silently swaps in the story's.
    expect(plugin.slug).toBeTypeOf("string");
    expect(plugin.slug.length).toBeGreaterThan(0);

    // THE ENGINE'S PLUGIN DELIBERATELY HAS NO TITLE, and that is the point of
    // it. It is worn by any number of stories at once, so a `title` here would
    // put one name in the tab of every story that ships no plugin -- which is
    // the exact bug it exists to replace. `loadStory` supplies the running
    // story's name from the catalogue instead.
    if (name === "_engine") {
      expect(plugin.title).toBeUndefined();
      return;
    }
    expect(plugin.title).toBeTypeOf("string");
    expect(plugin.title.length).toBeGreaterThan(0);
  });

  it("has a theme the loader can await", async () => {
    const plugin = (await load()).default;
    expect(plugin.theme).toBeTypeOf("function");
    // The loader does exactly this, and swallows a throw by discarding the
    // WHOLE plugin. A stylesheet that moved would cost the story every slot.
    await expect(plugin.theme()).resolves.toBeTruthy();
  });

  it("types every slot it declares", async () => {
    const plugin = (await load()).default;
    const slots = [
      "Mark", "HeaderBadge", "Aside", "Ledger", "Stage", "Toast",
      "MenuBanner", "Wrap", "StartIntro", "Wordmark", "Ending",
    ];
    for (const slot of slots) {
      if (plugin[slot] == null) continue;
      expect(isComponent(plugin[slot]), `${name}.${slot} is not a component`).toBe(true);
    }
    for (const fn of ["reduce", "bodyData", "hideChoices", "theme"]) {
      if (plugin[fn] == null) continue;
      expect(plugin[fn], `${name}.${fn} is not callable`).toBeTypeOf("function");
    }
    if (plugin.initialState != null) {
      expect(plugin.initialState).toBeTypeOf("object");
    }
    for (const list of ["overlays", "onboarding"]) {
      if (plugin[list] == null) continue;
      expect(Array.isArray(plugin[list]), `${name}.${list} is not an array`).toBe(true);
    }
  });

  it("declares well-formed overlays with unique shortcut keys", async () => {
    const plugin = (await load()).default;
    const overlays = plugin.overlays || [];
    const ids = new Set();
    const keys = new Set();

    for (const entry of overlays) {
      expect(entry.id, "an overlay with no id cannot be opened").toBeTypeOf("string");
      expect(ids.has(entry.id), `duplicate overlay id ${entry.id}`).toBe(false);
      ids.add(entry.id);

      // The footer renders `overlay.label` and falls back to its first
      // character when there is no Icon, so an unlabelled overlay is an
      // unlabelled button — unusable by voice or screen reader.
      expect(entry.label, `${entry.id} has no label`).toBeTypeOf("string");
      expect(entry.label.length).toBeGreaterThan(0);

      expect(isComponent(entry.Component), `${entry.id} has no Component`).toBe(true);
      if (entry.Icon != null) expect(isComponent(entry.Icon)).toBe(true);
      if (entry.when != null) expect(entry.when).toBeTypeOf("function");

      if (entry.key != null) {
        expect(entry.key).toBeTypeOf("string");
        // App lowercases once into a map; two entries claiming the same letter
        // means one shortcut is dead and nothing says which.
        const key = entry.key.toLowerCase();
        expect(keys.has(key), `two overlays claim "${key}" in ${name}`).toBe(false);
        // `/` focuses the compose box and Escape opens the pause menu, both in
        // core's global map, and a story cannot outrank them.
        expect(["/", "escape"]).not.toContain(key);
        keys.add(key);
      }
    }
  });

  it("returns the same slice when nothing moved", async () => {
    const plugin = (await load()).default;
    if (!plugin.reduce) return;

    const slice = plugin.initialState ?? {};
    // A client-only action the plugin has no business reacting to. Every
    // shipped plugin short-circuits on anything that is not SOCKET or RESET,
    // and the store compares identity to decide whether to rebuild `state`.
    const same = plugin.reduce(slice, { type: "REASONING_TOGGLE" }, {});
    expect(same, `${name}.reduce rebuilt its slice for an unrelated action`).toBe(slice);
  });

  it("resets to its own initial state, not to the previous run's", async () => {
    const plugin = (await load()).default;
    if (!plugin.reduce) return;
    const reset = plugin.reduce({ polluted: true }, { type: "RESET" }, {});
    expect(reset).toEqual(plugin.initialState ?? {});
  });

  it("renders every slot it declares against an empty world", async () => {
    // The SSR pass runs render functions and not effects, which is the right
    // half to check here: a slot that reads `state.world.location_id` on a
    // payload that has no world throws during render, and a throw in a slot is
    // not a blank panel -- it unmounts the client. Every story's FIRST paint
    // and every RESET is exactly this state.
    const plugin = (await load()).default;
    const state = {
      meters: {},
      world: null,
      busy: false,
      sessionId: "",
      sceneImage: "",
      log: [],
      choices: [],
      story: plugin.initialState ?? {},
    };
    const props = {
      state,
      busy: false,
      onCustom: () => {},
      onChoose: () => {},
      onOpenOverlay: () => {},
      onOpenMenu: () => {},
      showDiceBreakdown: true,
    };

    // `Wrap` takes children and `Ending` is a screen with its own props; both
    // are exercised by their own stories rather than pretended at here.
    const slots = [
      "Mark", "HeaderBadge", "Aside", "Ledger", "Stage",
      "Toast", "MenuBanner", "StartIntro", "Wordmark",
    ];
    for (const name of slots) {
      const Slot = plugin[name];
      if (!Slot) continue;
      expect(
        () => renderToStaticMarkup(React.createElement(Slot, props)),
        `${name} threw on an empty world`
      ).not.toThrow();
    }
  });

  it("survives an empty payload", async () => {
    const plugin = (await load()).default;
    if (!plugin.reduce) return;
    // A SOCKET action whose payload carries nothing this story declares. This
    // is not hypothetical: a resume, a reconnect replaying a partial payload,
    // and a story borrowing this plugin all produce it, and a reduce that
    // assumes its own keys throws inside the reducer -- which takes the whole
    // client down, not just the slot.
    expect(() =>
      plugin.reduce(plugin.initialState ?? {}, { type: "SOCKET" }, { world: null, meters: {} })
    ).not.toThrow();
  });
});

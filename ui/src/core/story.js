/**
 * The story plugin seam.
 *
 * WHY THIS EXISTS
 * ---------------
 * The client used to BE The Clockwork Dark. A d20 face, a hunger stage, four
 * evil phases and an Edgewood location table were welded into components with
 * names like "Scene" and "Sheet", so a second story could only ever reskin the
 * flagship. `games/` has held two stories for a while and the browser had one.
 *
 * A plugin is a plain object. Every field is optional: core has a working
 * default for all of them, which is what makes "a story that ships no plugin
 * still runs" true rather than aspirational -- `games/drowned-carillon/` is the
 * live proof, it has no plugin directory and boots on core alone.
 *
 * WHICH PLUGIN A STORY GETS
 * -------------------------
 * The server says. `GET /api/games` reports `ui_plugin` for the active story,
 * which is its manifest's `ui.plugin` or, when it declares none, its own slug --
 * so the default is exactly the old directory-name match.
 *
 * That indirection exists because a plugin directory is not free: Vite turns
 * each one into its own chunk in `content/scenes/clockwork/static/dist/`, which
 * is COMMITTED. A story that only wants to borrow another's look had no way to
 * say so, and paying for a directory plus build artefacts to get a skin that
 * already exists is the wrong trade. Now `ui: {plugin: wicked-garden}` in a
 * manifest is the whole of it.
 *
 * THE CONTRACT
 * ------------
 *   slug          The PLUGIN's own id. It no longer has to equal the running
 *                 story's slug -- two stories may share one plugin -- so
 *                 anything keying off "which story is this" must read the
 *                 catalogue, not this field.
 *   title         Fallback wordmark, used only until the catalogue answers.
 *   theme()       Returns a promise for the story's stylesheet. Loaded BEFORE
 *                 first paint, after core's, so story rules win ties without
 *                 anyone writing !important.
 *
 *   initialState  The story's own slice of the store, at `state.story`.
 *   reduce(slice, action, coreNext) -> slice
 *                 Runs after the core reducer on every action, with the already
 *                 -reduced core state so it can read the fresh turn payload.
 *                 Core never touches this slice; the story never touches core's.
 *   bodyData(state) -> {key: value}
 *                 Written onto document.body.dataset. This is how the flagship
 *                 gets `data-phase` without core knowing phases exist.
 *
 *   Mark          Masthead glyph, left of the header title.
 *   HeaderBadge   Right-hand header slot (the flagship's phase pill).
 *   Aside         Left column of the play screen.
 *   Ledger        Right column. Defaults to the declared-meter sheet.
 *   Stage         Top of the centre column, above the log.
 *   Toast         Free-floating layer over the play screen.
 *   MenuBanner    Top of the pause menu.
 *   Wrap          A provider around the whole client, for a story that needs
 *                 React context (the Garden's analyst mode is read ten levels
 *                 down and has no business being threaded as a prop).
 *   StartIntro    Copy block on the start screen.
 *   Wordmark      The start screen's title treatment.
 *   onboarding    Cards for the first-run shell. No cards, no first-run modal.
 *   overlays      [{id, key, label, Icon, Component}] -- one keyboard shortcut,
 *                 one footer button and one modal per entry.
 *   hideChoices(state) -> bool
 *                 The flagship suppresses the narrator's choices while an
 *                 encounter offers engine-authored approaches.
 *
 * Every slot is a React component and receives the same props object, so a
 * story can ignore the ones it does not care about: {state, dispatch, send,
 * story, busy, onOpenOverlay}.
 */

import { fetchGames } from "./api.js";

/**
 * Every story directory that ships an index.jsx, as lazy loaders.
 *
 * `import.meta.glob` is resolved by Vite at BUILD time and each match becomes
 * its own chunk, so one build carries every installed story and the runtime
 * picks -- no per-story rebuild, and a story nobody selects costs nothing but
 * disk. Adding a story is adding a directory.
 */
const PLUGINS = import.meta.glob("../stories/*/index.jsx");

/** Plugin id -> loader, keyed off the directory name under src/stories/. */
const BY_PLUGIN = Object.fromEntries(
  Object.entries(PLUGINS).map(([path, load]) => [
    path.replace("../stories/", "").replace("/index.jsx", ""),
    load,
  ])
);

/** The plugin a story gets when it ships none. Pure core. */
export const CORE_ONLY = Object.freeze({
  slug: "",
  title: "",
  initialState: {},
  onboarding: [],
  overlays: [],
});

export function listStories() {
  return Object.keys(BY_PLUGIN);
}

/**
 * Load one plugin and its theme, or fall back to core.
 *
 * Never rejects. A story whose plugin throws must cost the player its bespoke
 * screens, not the boot -- core alone is a playable client.
 *
 * Args:
 *   plugin  Which plugin directory to load.
 *   slug    The running story, for the fallback `slug` field and log lines.
 *           Defaults to the plugin id, which is the case for every story that
 *           declares no `ui.plugin`.
 *   title   The running story's own name, from the catalogue. Only used when
 *           the plugin is BORROWED -- see below.
 */
export async function loadStory(plugin, slug = plugin, title = "") {
  const loader = BY_PLUGIN[plugin];
  if (!loader) return CORE_ONLY;
  try {
    const module = await loader();
    const found = module.default || CORE_ONLY;
    if (found.theme) await found.theme();

    // A BORROWED plugin lends its LOOK, not its VOICE.
    //
    // A plugin holds two kinds of thing. Visual slots -- theme, Ledger, Stage,
    // Wrap, components -- are what a story borrows one for. Naming slots are
    // copy written in that story's own fiction, and they assert whose story
    // this is: `title` and `documentTitle` reach the tab and the masthead,
    // `Wordmark` is the start screen's title treatment, `beginLabel` is a
    // sentence about a specific world ("Step through the hedge"), `StartIntro`
    // and `onboarding` are prose about it.
    //
    // Left alone, a scratch story borrowing the Garden's skin announced itself
    // as The Wicked Garden everywhere and invited the player to step through a
    // hedge that is not in its one room. Stripped, it gets the look it asked
    // for and its own name. When the plugin is the story's own -- every shipped
    // story -- none of this runs.
    const borrowed = plugin !== slug;
    const naming = borrowed
      ? {
          title: title || slug,
          documentTitle: title || slug,
          Wordmark: null,
          StartIntro: null,
          beginLabel: "",
          asideLabel: "",
          onboarding: [],
        }
      : {};

    return { ...CORE_ONLY, ...found, ...naming, slug: found.slug || slug };
  } catch (err) {
    console.error(`[story] plugin "${plugin}" failed to load; falling back to core`, err);
    return CORE_ONLY;
  }
}

/**
 * Ask the server which story is running, then load its plugin.
 *
 * The catalogue is the single source of truth for "which story": activation is
 * a launch-time decision on the server (swapping stories under a live session
 * would invalidate every save mid-turn), so the client's job is to follow, not
 * to choose.
 */
export async function resolveStory() {
  let slug = "";
  let plugin = "";
  let title = "";
  try {
    const data = await fetchGames();
    const games = data?.games || [];
    const active = games.find((g) => g.active) || null;
    slug = data?.active || active?.slug || "";
    // What the story ASKED to be drawn as. The server already defaults this to
    // the story's own slug, so the lookup below is the old behaviour whenever a
    // manifest declares nothing.
    plugin = active?.ui_plugin || "";
    title = active?.title || "";
  } catch {
    // No catalogue route, or the server is not up yet. A single-story install
    // with a plugin still resolves below if there is exactly one on disk.
  }
  if (!slug) {
    const only = listStories();
    if (only.length === 1) slug = only[0];
  }
  return loadStory(plugin || slug, slug, title);
}

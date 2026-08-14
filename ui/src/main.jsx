/**
 * Client entry.
 *
 * Two steps and nothing else: ask the server which story is running, load that
 * story's plugin (screens, theme, novel components), then mount core with it.
 *
 * The resolve happens BEFORE first paint on purpose. The plugin's stylesheet
 * loads inside `resolveStory`, so the first frame the player sees is already
 * themed rather than a neutral core flash that repaints a beat later.
 *
 * A story with no plugin, a plugin that throws, or a server with no catalogue
 * all land in the same place: core alone, which is a complete client.
 *
 * No shipped story exercises that path: both declare `ui: {plugin: ...}` in
 * their manifests and ship the plugin they name. It exists for the story that
 * is a directory and a game.yaml and nothing else yet, and it is held by
 * `tests/test_story_surface.py` rather than by a game somebody plays. Worth
 * knowing: a path proved only by a test is a path that rots more quietly than
 * one a player walks.
 */
import React from "react";
import { createRoot } from "react-dom/client";

import App from "./core/App.jsx";
import { resolveStory } from "./core/story.js";

// Core's own stylesheet. The story's loads on top of it, from the plugin.
import "./styles/index.css";

// A demo route for component kits that have no story to run inside yet. Kept
// out of the game path entirely: it is reached only by an explicit ?kit= and
// costs a lazily-loaded chunk that a player never fetches.
const kit = new URLSearchParams(window.location.search).get("kit");

// The authoring studio, on the same terms as the kit: an explicit query param
// and a lazily-loaded chunk a player never fetches. The ROUTES it talks to
// exist only on a server started with `launcher.py --studio`, so this screen
// on an ordinary server is a set of failed fetches rather than a way in.
const studio = new URLSearchParams(window.location.search).get("studio");

const root = createRoot(document.getElementById("root"));

if (studio) {
  Promise.all([import("./studio/Studio.jsx"), import("./studio/studio.css")])
    .then(([{ default: Studio }]) => {
      // Not "Studio — <a story>": this tool edits every story on the machine,
      // so naming one in the tab is the same mistake as core's stylesheet
      // wearing the flagship's title, which is what the gate in
      // tests/test_no_story_literals_in_core_ui.py exists to catch. It caught
      // this line.
      document.title = "Studio";
      root.render(<Studio />);
    })
    .catch((err) => {
      console.error("[studio] failed to load", err);
      root.render(<p style={{ padding: 24 }}>The studio would not load.</p>);
    });
} else if (kit) {
  import("./kits.jsx")
    .then(({ default: mountKit }) => mountKit(root, kit))
    .catch((err) => {
      console.error("[kit] failed to load", err);
      root.render(<p style={{ padding: 24 }}>No component kit called “{kit}”.</p>);
    });
} else {
  resolveStory().then((story) => {
    const name = story.documentTitle || story.title || "";
    document.title = name || document.title;
    // The overlay eyebrow (.overlay__title::before) is CSS `content`, and the
    // flagship's name was TYPED INTO IT -- so every overlay in every story
    // announced "THE CLOCKWORK DARK", including a funeral-barge story that
    // borrows the Garden's skin. It is set here rather than per theme because
    // this is the one place that already knows which story is running, and
    // because it must also be right for a BORROWED plugin, where `loadStory`
    // has deliberately replaced the lender's naming slots with the borrower's.
    //
    // `content` needs a QUOTED string; JSON.stringify supplies the quotes and
    // escapes any inside the title. An empty name leaves the var unset-ish and
    // the CSS fallback ("") draws nothing, which is the right answer for a
    // story whose title we could not resolve.
    document.documentElement.style.setProperty("--story-eyebrow", JSON.stringify(name));
    root.render(<App story={story} />);
  });
}

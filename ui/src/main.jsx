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
 * `games/drowned-carillon/` is the live case -- it has no directory under
 * src/stories/ and it boots.
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

const root = createRoot(document.getElementById("root"));

if (kit) {
  import("./kits.jsx")
    .then(({ default: mountKit }) => mountKit(root, kit))
    .catch((err) => {
      console.error("[kit] failed to load", err);
      root.render(<p style={{ padding: 24 }}>No component kit called “{kit}”.</p>);
    });
} else {
  resolveStory().then((story) => {
    document.title = story.documentTitle || story.title || document.title;
    root.render(<App story={story} />);
  });
}

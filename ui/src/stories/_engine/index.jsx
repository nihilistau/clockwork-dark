/**
 * The engine's own plugin — what a story gets when it ships none.
 *
 * WHY THIS EXISTS. `CORE_ONLY` was a fallback, not a skin: no theme, no
 * wordmark, no onboarding. A story with no plugin of its own therefore had two
 * options, and both were bad. Run on bare core and look unfinished, or declare
 * `ui.plugin: wicked-garden` and inherit somebody else's VOICE along with
 * their spacing — which is how a funeral-barge story came to offer a screen
 * called "The court" and draw a fae court's cast in it.
 *
 * So the third option is this: a real plugin that belongs to the engine and
 * deliberately has no world. It is the honest starting point for a new story
 * and the permanent home for one that never wants its own look.
 *
 * WHAT IT DOES NOT DO, on purpose:
 *
 *   - No `Ledger`, `Stage`, `Aside` or `Toast`. Core's defaults are complete
 *     and correct; overriding them here would make this a fifth aesthetic
 *     rather than the absence of one.
 *   - No `title` or `documentTitle`. The running story's own name comes from
 *     the catalogue, and hardcoding one here would put "The Engine" in the
 *     browser tab of every undressed story — exactly the bug this replaces.
 *   - No overlays. Core supplies the map; anything else is a claim about what
 *     this story contains, and this plugin knows nothing about that.
 */
import React from "react";

/**
 * A wordmark that is the story's own name, set in the narration face.
 *
 * Reads `title` from props rather than a constant: this plugin is worn by any
 * number of stories at once and must never speak for a particular one.
 */
function Wordmark({ title }) {
  return <span className="wordmark--engine">{title || "A story"}</span>;
}

export default {
  slug: "_engine",

  theme: () => import("./theme/engine.css"),

  // The single attribute the palette hangs off. Scoped rather than global so
  // that loading this sheet can never recolour a story that has its own.
  bodyData: () => ({ storySkin: "engine" }),

  Wordmark,

  // Two cards, and they describe the ENGINE's contract rather than any
  // fiction: what a turn is, and that the world keeps moving. A story with its
  // own onboarding replaces these; a story without one should still be told
  // how the thing works.
  onboarding: [
    {
      id: "how-a-turn-works",
      title: "How a turn works",
      body:
        "Pick one of the offered choices, or type what you do. The engine " +
        "resolves anything that moves, spends or risks something before a " +
        "word is written, so what you read is what actually happened.",
    },
    {
      id: "the-world-keeps-time",
      title: "The world keeps time",
      body:
        "Hours pass when you travel, work or rest, and things happen while " +
        "you decide. Your save holds all of it — leave whenever you like.",
    },
  ],
};

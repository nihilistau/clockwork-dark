/**
 * HUE & CRY's skin (v0.21.0, spec §9).
 *
 * A SKIN, NOT A SCREEN SET. It fills no component slot -- no Stage, Ledger,
 * Aside, Toast or overlay -- and owns no panel: everything on the play screen
 * is the engine's (the poster, the casing board, the job, the people here,
 * the watch stop's approaches, the roll card), declared by data in
 * games/hue-and-cry/game.yaml's `ui.panels`, and worn here under wax and
 * parchment. That is the proof the panels are themeable by a real story's
 * tokens and not only by `_engine`'s neutral ones. `defaultStage` gives it
 * core's scene plate. Its art pack -- portraits included -- is v1.0 work;
 * until then the people strip draws monograms.
 */
import React from "react";

/** The title set as a printed bill. */
function Wordmark({ title }) {
  return (
    <span className="wordmark--bill">
      <span className="bill__rule" aria-hidden="true" />
      <span className="bill__title">{title || "HUE & CRY"}</span>
      <span className="bill__rule" aria-hidden="true" />
    </span>
  );
}

export default {
  slug: "hue-and-cry",
  title: "HUE & CRY",
  documentTitle: "HUE & CRY",
  beginLabel: "Step off the barge",

  theme: () => import("./theme/hue-and-cry.css"),

  // Scoped, like `_engine`'s, so loading this sheet can never recolour another story.
  bodyData: () => ({ storySkin: "hue-and-cry" }),

  Wordmark,

  // Core's scene plate (spec §3.3): this skin has no Stage of its own.
  defaultStage: true,

  onboarding: [
    {
      id: "the-watch-has-decided",
      title: "The Watch has decided",
      body:
        "The Lantern Watch has decided you are the Magpie. Each part of the city keeps its own " +
        "opinion of how badly it wants you, and the poster on your sheet shows how clearly the " +
        "watch where you stand could draw your face.",
    },
    {
      id: "pip",
      title: "Pip",
      body:
        "A one-eyed jackdaw has decided you are his. He has opinions about all of this, and he " +
        "will share them.",
    },
    {
      id: "the-city-keeps-its-hours",
      title: "The city keeps its hours",
      body:
        "Houses empty and fill by the clock. Casing a house teaches you when, and what is " +
        "inside; the casing board keeps what you have learned, and says when a house is empty now.",
    },
  ],
};

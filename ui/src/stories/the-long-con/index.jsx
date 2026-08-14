/**
 * THE LONG CON — story plugin.
 *
 * Small by intent. The engine now supplies everything a story needs to be
 * playable — map, clue board, meters, log — so a plugin's whole job is the
 * things that are true of THIS city and no other: what it is called, what the
 * light looks like, and the two words on the Begin button.
 *
 * The mark is the office door's frosted glass with a name on it, and the name
 * has one too many Vances in it. That is the premise in one glyph: the man
 * you are is still trading under a dead man's name.
 */
import React from "react";

/** VANCE & VANCE on frosted glass, the second one fainter than the first. */
function DoorMark() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <rect
        x="4.5"
        y="2.5"
        width="15"
        height="19"
        rx="1"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
      />
      <path d="M7.5 9h9M7.5 12h9" stroke="currentColor" strokeWidth="1" opacity="0.85" />
      <path d="M7.5 15h9" stroke="currentColor" strokeWidth="1" opacity="0.35" />
    </svg>
  );
}

function Wordmark() {
  return (
    <span className="longcon-wordmark">
      THE LONG CON
    </span>
  );
}

function StartIntro() {
  return (
    <p className="longcon-intro">
      Two rooms over a laundry, a name on the glass with one too many Vances in
      it, and a client who has not taken off her gloves. The papers buried the
      man in her photograph nine days before it was taken.
    </p>
  );
}

export default {
  slug: "the-long-con",
  title: "THE LONG CON",
  documentTitle: "THE LONG CON",
  beginLabel: "Take the case",

  theme: () => import("./theme/long-con.css"),

  // One attribute, and the whole product retones. Core writes it and has no
  // idea what a skin is.
  bodyData: () => ({ storySkin: "longcon" }),

  Mark: DoorMark,
  Wordmark,
  StartIntro,

  // NO OVERLAYS OF ITS OWN. The map and the clue board are core's now, and
  // both are exactly what this story wants: a city to cross and somewhere to
  // keep what you worked out. Declaring its own `map` would replace a working
  // screen with a worse one to prove a point.
  onboarding: [
    {
      id: "the-city-keeps-books",
      title: "The city keeps books on everybody",
      body:
        "The paper files the dead by name. The precinct files the living. The " +
        "club files what people owe. Every one of those ledgers is missing " +
        "exactly one page, and finding out which is the job.",
    },
    {
      id: "what-you-know",
      title: "What you know is not what is true",
      body:
        "Half this cast is lying at any given moment. What you piece together " +
        "collects on your own board — press K — and it is yours, not theirs " +
        "and not the city's.",
    },
  ],
};

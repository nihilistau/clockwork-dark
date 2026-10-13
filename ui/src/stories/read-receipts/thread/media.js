/**
 * Readers of a message's media (spec §13, §18.2): where a file may be loaded
 * from, how long a voice note runs, and the waveform a voice tile draws.
 *
 * A media `src` comes ONLY from the server's media route
 * (`/api/phone/media/<save_id>/<name>`, engine/media/comfy/storage.py
 * `url_for`): any other value -- another host, a `data:` or `javascript:`
 * URL, a path out of the route -- is treated as no file, and the tile draws
 * its procedural stand-in instead.
 */
import { hueOf } from "../phone/format.js";

const MEDIA_URL = /^\/api\/phone\/media\/[A-Za-z0-9_.-]{1,128}\/[A-Za-z0-9_-]{1,64}\.(png|jpg|webp|mp4|webm|wav)$/;

/** The URL if it is one of the media route's, else "". */
export function mediaSrc(url) {
  const text = typeof url === "string" ? url : "";
  return MEDIA_URL.test(text) && !text.includes("..") ? text : "";
}

/** A voice note's seconds as "0:07". */
export function durationOf(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** A fixed waveform for a media id: `bars` heights between 0.25 and 1, the same every time. */
export function waveOf(id, bars = 28) {
  let seed = hueOf(id) + 1;
  const out = [];
  for (let i = 0; i < bars; i += 1) {
    seed = (seed * 9301 + 49297) % 233280;
    out.push(0.25 + 0.75 * (seed / 233280));
  }
  return out;
}

/** The asks the compose bar offers (spec §7.1's `ask`), in its menu's words. */
export const ASK_MENU = [
  ["number", "Their number"],
  ["photo", "A photo"],
  ["voice", "A voice note"],
  ["video", "A video"],
  ["meet", "To meet up"],
  ["exclusive", "To be exclusive"],
];

/** The games' names (games.yaml's labels, for a request that names only its id). */
export const GAME_WORDS = { wordgame: "Tile Talk", this_or_that: "This or That" };

const ONE_OF = { photo: "a photo", voice: "a voice note", video: "a video" };

/** An ask told in words: the player's (`mine`) or theirs (`who` is their name). */
export function askLine(what, who, mine, game = "") {
  const named = GAME_WORDS[game] || "";
  switch (what) {
    case "number":
      return mine ? `You asked ${who} for their number.` : `${who} asked for your number.`;
    case "exclusive":
      return mine ? `You asked ${who} to be exclusive.` : `${who} asked to be exclusive.`;
    case "meet":
      return mine ? `You asked ${who} to meet up.` : `${who} asked to meet up.`;
    case "game":
      return mine ? `You invited ${who} to ${named || "a game"}.` : `${who} invited you to ${named || "a game"}.`;
    default:
      if (ONE_OF[what]) return mine ? `You asked ${who} for ${ONE_OF[what]}.` : `${who} asked you for ${ONE_OF[what]}.`;
      return mine ? `You asked ${who} something.` : `${who} asked you something.`;
  }
}

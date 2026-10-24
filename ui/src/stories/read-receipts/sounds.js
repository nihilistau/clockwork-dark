/**
 * READ RECEIPTS' sounds (v0.24.0 spec §9.7): one message, one sound; nothing for what an opening replays.
 * A message is keyed by its thread and time (Plan decision 1): the one key both carriers share.
 */
import { markSeen, playSound } from "@core/sound/index.js";

export const SOUND_EVENTS = Object.freeze([
  "phone.message_in", "phone.notify", "phone.buzz", "phone.ring", "phone.typing", "phone.send",
  "phone.unlock", "phone.lock", "phone.up", "phone.down", "phone.match", "phone.swipe", "scene.open",
]);
const RANK = ["phone.ring", "phone.buzz", "phone.message_in", "phone.notify"];
const DATING = new Set(["matchstick", "front_porch"]);              // phone/apps.js's dating apps (F14)

export const messageKey = (row) => `msg:${row.thread_id}@${row.last.at}`;
const matchKey = (row) => `match:${row.thread_id}`;
const sceneKey = (scene) => `scene:${scene.id}`;
const rows = (phone) => (phone && Array.isArray(phone.threads) ? phone.threads : []);
const fromThem = (row) => row.last && row.last.from !== "player" && !row.last.pending;

/** Every opening (a start, a resume, a rejoin): everything already on the phone is seen, and makes no sound. */
export function hydrate(phone) {
  const keys = [];
  for (const row of rows(phone)) {
    keys.push(matchKey(row));
    if (row.last && !row.last.pending) keys.push(messageKey(row));   // an unvoiced one is still to arrive
  }
  if (phone && phone.scene && phone.scene.id) keys.push(sceneKey(phone.scene));
  markSeen(keys);
}

/** A row's newest message is fresh: from them, voiced, and new or newly voiced (pre-flight F2). */
function fresh(old, row) {
  if (!fromThem(row)) return false;
  return !old || !old.last || old.last.at !== row.last.at || Boolean(old.last.pending);
}

/** The sounds for what changed between two phone blocks. */
export function phoneSounds(prev, next, { openThread, up }) {
  const before = new Map(rows(prev).map((r) => [r.thread_id, r]));
  const found = [];
  for (const row of rows(next)) {
    const old = before.get(row.thread_id);
    if (!old && rows(prev).length && !row.last && DATING.has(row.app)) playSound("phone.match", { key: matchKey(row) });
    if (!fresh(old, row)) continue;
    const kind = row.last.kind;
    const event = kind === "voice" || kind === "video" ? "phone.ring"
      : !up ? "phone.buzz" : row.thread_id === openThread ? "phone.message_in" : "phone.notify";
    found.push({ event, key: messageKey(row) });
  }
  if (found.length) {
    found.sort((a, b) => RANK.indexOf(a.event) - RANK.indexOf(b.event));
    const [top, ...rest] = found;
    playSound(top.event, { key: top.key });
    markSeen(rest.map((f) => f.key));
  }
  const scene = next && next.scene;
  if (scene && scene.id) playSound("scene.open", { key: sceneKey(scene) });
}

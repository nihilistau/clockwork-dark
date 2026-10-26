/**
 * READ RECEIPTS' sounds (v0.24.0 spec §9.7): one message, one sound; nothing for what an opening replays.
 * A message is keyed by its thread and time (Plan decision 1): the one key both carriers share.
 */
import { markSeen, noteArrivalCue, playSound } from "@core/sound/index.js";

export const SOUND_EVENTS = Object.freeze([
  "phone.message_in", "phone.notify", "phone.buzz", "phone.ring", "phone.typing", "phone.send",
  "phone.unlock", "phone.lock", "phone.up", "phone.down", "phone.match", "phone.swipe", "scene.open",
]);
const RANK = ["phone.ring", "phone.buzz", "phone.message_in", "phone.notify"];
// The dating apps are the payload's own (`phone.apps` rows of kind "dating"), never a literal list (T14 d6).
const datingApps = (phone) => new Set((phone && Array.isArray(phone.apps) ? phone.apps : []).filter((a) => a && a.kind === "dating").map((a) => a.id));

export const messageKey = (row) => `msg:${row.thread_id}@${row.last.at}`;
const matchKey = (row) => `match:${row.thread_id}`;
const sceneKey = (scene) => `scene:${scene.id}`;
const rows = (phone) => (phone && Array.isArray(phone.threads) ? phone.threads : []);
// An engine line ("{name} is in", an expiry) is `from: "system"`: it is no one's message and never sounds (T14 d3).
const fromThem = (row) => row.last && row.last.from !== "player" && row.last.from !== "system" && !row.last.pending;

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

/** A play the ledger did not drop as already heard: the arrival is new. */
const isNew = (entry) => !(entry && entry.dropped === "seen");

/**
 * The sounds for what changed between two phone blocks. Returns the VISIBLE counterparts that go with them
 * (spec §7: a sound is never the only signal): `notices`, one per match ("match") and, for the sound that
 * plays, a message that landed in a thread other than the open one while the phone is up ("message"). A
 * phone that is down has the world layer's buzz banner instead.
 */
export function phoneSounds(prev, next, { openThread, up }) {
  const before = new Map(rows(prev).map((r) => [r.thread_id, r]));
  const dating = datingApps(next);
  const found = [];
  const matches = [];
  const notices = [];
  for (const row of rows(next)) {
    const old = before.get(row.thread_id);
    if (!old && !row.last && dating.has(row.app)) matches.push(row);
    if (!fresh(old, row)) continue;
    const kind = row.last.kind;
    const event = kind === "voice" || kind === "video" ? "phone.ring"
      : !up ? "phone.buzz" : row.thread_id === openThread ? "phone.message_in" : "phone.notify";
    found.push({ event, key: messageKey(row), row });
  }
  // One sound per arrival (T14 d7): the scene's door first, then the phone's cue; the rest are marked heard.
  const scene = next && next.scene;
  const door = Boolean(scene && scene.id) && isNew(playSound("scene.open", { key: sceneKey(scene) }));
  let cued = door;
  for (const row of matches) {
    if (isNew(door ? markedSeen(matchKey(row)) : playSound("phone.match", { key: matchKey(row) }))) {
      notices.push({ kind: "match", thread_id: row.thread_id, name: row.name || "", app: row.app });
      cued = true;
    }
  }
  if (found.length) {
    found.sort((a, b) => RANK.indexOf(a.event) - RANK.indexOf(b.event));
    const [top, ...rest] = found;
    const played = door || cued ? markedSeen(top.key) : playSound(top.event, { key: top.key });
    markSeen(rest.map((f) => f.key));
    if (isNew(played)) {
      cued = true;
      if (up && top.row.thread_id !== openThread) {
        notices.push({ kind: "message", thread_id: top.row.thread_id, name: top.row.name || "", preview: top.row.last.preview || "" });
      }
    }
  }
  if (cued) noteArrivalCue();
  return { notices };
}

/** Heard without a sound: the key is remembered; the entry says it is new (so its visible counterpart shows). */
function markedSeen(key) {
  markSeen([key]);
  return { dropped: "superseded" };
}

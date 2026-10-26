/**
 * READ RECEIPTS' slice of the store (v0.22.0 spec §18.2).
 *
 * Core gives a plugin no `dispatch` (story.js's contract), so the slice holds
 * only what the reducer can see: the background pushes kept until the next
 * full payload supersedes them, the counters `usePhoneAct` watches, what core
 * reported as never sent, and the lock screen's words for a run just opened.
 * Navigation (which app, which thread) and the action in flight live in
 * `PlayScreen`'s own React state.
 *
 * Every merge here is IDEMPOTENT: a push applied twice, or a `media_ready`
 * that arrives before the `phone_message` carrying its message, leaves the
 * phone exactly as one in-order delivery would.
 */

export const initialState = Object.freeze({
  pushes: [],
  busySeq: 0,
  turnSeq: 0,
  dropSeq: 0,
  dropped: [],
  lockSeq: 0,
  // Bumped on EVERY game_started/game_resumed, a rejoin included: the sound hydration's cue (v0.24.0 F12).
  openSeq: 0,
  lock: null,
  sessionId: "",
  // A world choice the server refused because the phone is up (409 `phone_up`): counted, with its words.
  upSeq: 0,
  upWords: "",
});

/**
 * How many pushes are kept between two full payloads (every `turn_update`
 * and run opening clears them). Past it the OLDEST is dropped: what it
 * carried is missing from the phone until the next payload brings it whole.
 * A voicing pass pushes one message per reply, so fifty between two of the
 * player's own actions is far past any pass the data makes today.
 */
export const MAX_PUSHES = 50;
/** The payload's own cap on notifications (`social.notifications_max`). */
const MAX_NOTIFICATIONS = 30;

/**
 * The phone's slice. Core's turn_error keeps only `state.error` (a string)
 * for a busy answer, so the plugin counts the busy answers that reach the
 * store itself -- each one is FINAL: core's sender already re-sent the action
 * once and swallowed the first busy (core/socket.js, spec §18.2).
 */
export function reduce(slice, action, next) {
  const s = slice || initialState;
  if (!action) return s;
  if (action.type === "RESET") return initialState;
  if (action.type === "PHONE_DROPPED") {
    const intents = Array.isArray(action.intents) ? action.intents : [];
    return intents.length ? { ...s, dropSeq: s.dropSeq + 1, dropped: intents } : s;
  }
  if (action.type !== "SOCKET") return s;
  const payload = action.payload || {};
  switch (action.event) {
    case "phone_message":
      return { ...s, pushes: [...s.pushes.slice(-(MAX_PUSHES - 1)), { via: "message", body: payload }] };
    case "media_ready":
      return { ...s, pushes: [...s.pushes.slice(-(MAX_PUSHES - 1)), { via: "media", body: payload }] };
    case "turn_update": {
      // A full payload supersedes the pushes it already holds. A push it
      // does NOT hold yet is kept: the voicing pass can build and deliver a
      // push after the mechanics built this payload but before it arrived
      // (server threads, review M3 of T27), and clearing it would leave a
      // reply on "…" until the next payload. An answer core credits to no
      // action (`stale`, a timed-out action's late one) is still a full
      // payload, but answers nothing of ours.
      const phone = payload.state && payload.state.phone;
      const kept = keptPushes(s.pushes, phone);
      return { ...s, pushes: kept, turnSeq: action.stale ? s.turnSeq : s.turnSeq + 1 };
    }
    case "turn_error":
      // A busy answer that reaches the store is the second one: the action
      // is not sent. Any other turn_error answered it (a refusal, a fault).
      if (action.stale) return s;
      if (payload.phone_up) return { ...s, upSeq: s.upSeq + 1, upWords: String(payload.message || "Put the phone down first."), turnSeq: s.turnSeq + 1 };
      return payload.busy ? { ...s, busySeq: s.busySeq + 1 } : { ...s, turnSeq: s.turnSeq + 1 };
    case "game_started":
    case "game_resumed":
      // A late answer for the run on screen is a no-op in core (it keeps its world); the phone's slice
      // mirrors it, so the pushes kept since the last turn_update are not thrown away for nothing (T14 b4).
      if (action.event === "game_started" && next && payload.state && next.world !== payload.state
        && payload.session_id && String(payload.session_id) === s.sessionId) return s;
      return opened(s, action.event, payload);
    default:
      return s;
  }
}

/**
 * The pushes a full payload's phone block (`phone`) does not already hold:
 * a message push whose thread row is newer than the payload's (a later
 * `last`, or a voiced one over the payload's "…"), or whose messages the
 * payload's open thread lacks or shows unvoiced; a media push whose message
 * the payload shows still sending (or not yet voiced), or which belongs to a
 * message push kept here. A thread the payload no longer lists keeps nothing:
 * the payload is the authority on what exists. With no phone block, none.
 */
export function keptPushes(pushes, phone) {
  if (!phone || !Array.isArray(pushes) || !pushes.length) return [];
  const kept = pushes.filter((p) => p.via === "message" && messageAhead(p.body || {}, phone));
  const keptIds = new Set();
  for (const p of kept) for (const m of messagesOf(p.body || {})) keptIds.add(m.id);
  return pushes.filter((p) => (p.via === "message" ? kept.includes(p) : p.via === "media" && mediaAhead(p.body || {}, phone, keptIds)));
}

function messagesOf(body) {
  const list = Array.isArray(body.messages) && body.messages.length ? body.messages : body.message ? [body.message] : [];
  return list.filter((m) => m && m.id);
}

function messageAhead(body, phone) {
  const row = body.thread;
  if (!row || !row.thread_id) return false;
  const held = (phone.threads || []).find((t) => t.thread_id === row.thread_id);
  if (!held) return false;
  const open = phone.open_thread && phone.open_thread.thread_id === row.thread_id ? phone.open_thread : null;
  if (open) {
    const shown = Array.isArray(open.messages) ? open.messages : [];
    for (const m of messagesOf(body)) {
      const had = shown.find((x) => x.id === m.id);
      if (!had || (had.pending && !m.pending)) return true;
    }
  }
  const a = lastAt(row);
  const b = lastAt(held);
  return a > b || (a === b && Boolean(held.last && held.last.pending) && Boolean(row.last) && !row.last.pending);
}

function mediaAhead(body, phone, keptIds) {
  if (!body.message_id) return false;
  if (keptIds.has(body.message_id)) return true;
  const open = phone.open_thread;
  const m = open && Array.isArray(open.messages) ? open.messages.find((x) => x.id === body.message_id) : null;
  if (!m) return false;
  return !m.media || m.media.status === "sending";
}

/**
 * A run opened: a new game, a resume, or a rejoin of the run on screen.
 * Only a run this page did not already show (a new session id) or a resume
 * puts the phone back on its lock screen -- a rejoin after a dropped socket
 * must not throw the player out of the thread they were typing in.
 */
function opened(s, event, payload) {
  const sessionId = String(payload.session_id || "");
  const fresh = event === "game_resumed" || (sessionId && sessionId !== s.sessionId);
  if (!fresh) return { ...s, openSeq: s.openSeq + 1, pushes: s.pushes.length ? [] : s.pushes };
  const opening = payload.opening || {};
  const lockScreen = opening.lock_screen || null;
  const text = (lockScreen && lockScreen.text) || (event === "game_started" ? String(opening.narration || "") : "");
  return {
    ...s,
    pushes: [],
    sessionId,
    openSeq: s.openSeq + 1,
    lockSeq: s.lockSeq + 1,
    lock: { text, lines: Array.isArray(lockScreen?.lines) ? lockScreen.lines : [] },
  };
}

/**
 * The phone block as the player sees it now: the last payload's
 * (`state.world.phone`, core's copy of `to_client_dict`), with the later
 * pushes applied IN ARRIVAL ORDER, so the newest thread row wins. Then each
 * media push's fields are applied once more (never its row): a photo
 * finished before its message arrived still lands on it.
 */
export function currentPhone(state) {
  const base = state && state.world && state.world.phone;
  if (!base) return null;
  const pushes = (state.story && state.story.pushes) || [];
  if (!pushes.length) return base;
  const applied = pushes.reduce(applyPush, base);
  return pushes.filter((p) => p.via === "media").reduce((phone, p) => withMedia(phone, p.body || {}), applied);
}

/** One push applied to a phone block; a new object, the old one untouched. */
export function applyPush(phone, push) {
  const body = (push && push.body) || {};
  let next = phone;
  if (body.thread && body.thread.thread_id) {
    // A message push's row is the thread now. A media push's row was built
    // when the file finished, and is taken only when it is not older than
    // the row already held.
    const held = (next.threads || []).find((t) => t.thread_id === body.thread.thread_id);
    if (push.via === "message" || !held || lastAt(body.thread) >= lastAt(held)) next = withThreadRow(next, body.thread);
  }
  if (push.via === "message") {
    if (body.badges && typeof body.badges === "object") next = withBadges(next, body.badges);
    if (body.notification && body.notification.id) next = withBuzz(next, body.notification);
    if (body.notification && body.notification.id) next = withNotification(next, body.notification);
    const list = Array.isArray(body.messages) && body.messages.length ? body.messages : body.message ? [body.message] : [];
    if (body.thread && body.thread.thread_id) next = withMessages(next, body.thread, list);
  } else if (push.via === "media" && body.message_id) {
    next = withMedia(next, body);
  }
  return next;
}

const lastAt = (row) => (row && row.last && typeof row.last.at === "number" ? row.last.at : -1);

function withThreadRow(phone, row) {
  const threads = Array.isArray(phone.threads) ? phone.threads : [];
  const at = threads.findIndex((t) => t.thread_id === row.thread_id);
  const merged = at >= 0 ? threads.map((t, i) => (i === at ? row : t)) : [row, ...threads];
  // Latest first, as the payload's own section sorts them; stable for ties.
  const sorted = merged
    .map((t, i) => [t, i])
    .sort((a, b) => lastAt(b[0]) - lastAt(a[0]) || a[1] - b[1])
    .map(([t]) => t);
  const open = phone.open_thread;
  const openThread = open && open.thread_id === row.thread_id ? { ...open, typing: Boolean(row.typing), open: row.open !== false } : open;
  return { ...phone, threads: sorted, open_thread: openThread };
}

function withBadges(phone, badges) {
  const apps = Array.isArray(phone.apps) ? phone.apps : [];
  return { ...phone, apps: apps.map((a) => ({ ...a, badge: Number(badges[a.id] || 0) })) };
}

/**
 * The buzz banner, from the push (T14 d1): a voiced message that lands while the phone is down raises the
 * count and adds the name -- once per notification (the payload may already hold it, as "New message", and
 * its own count with it). Names only, as the engine's `buzz` sends them.
 */
function withBuzz(phone, row) {
  const world = phone.world;
  if (!world || world.phone_up !== false) return phone;
  if ((phone.notifications || []).some((n) => n.id === row.id)) return phone;
  const buzz = world.buzz && typeof world.buzz === "object" ? world.buzz : { count: 0, who: [] };
  const who = Array.isArray(buzz.who) ? buzz.who : [];
  const name = typeof row.name === "string" ? row.name : "";
  return {
    ...phone,
    world: { ...world, buzz: { ...buzz, count: (Number(buzz.count) || 0) + 1, who: name && !who.includes(name) ? [...who, name] : who } },
  };
}

function withNotification(phone, row) {
  const rows = Array.isArray(phone.notifications) ? phone.notifications : [];
  // A row already held is replaced in its place (T30): the payload listed it while its
  // message was still being written ("New message"); the voicing pass's push carries
  // the same id with the words now written.
  if (rows.some((n) => n.id === row.id)) return { ...phone, notifications: rows.map((n) => (n.id === row.id ? row : n)) };
  return { ...phone, notifications: [...rows, row].slice(-MAX_NOTIFICATIONS) };
}

function withMessages(phone, thread, list) {
  const open = phone.open_thread;
  if (!open || open.thread_id !== thread.thread_id || !list.length) return phone;
  const messages = Array.isArray(open.messages) ? [...open.messages] : [];
  for (const m of list) {
    if (!m || !m.id) continue;
    const at = messages.findIndex((x) => x.id === m.id);
    if (at >= 0) messages[at] = m;
    else messages.push(m);
  }
  return { ...phone, open_thread: { ...open, messages } };
}

function withMedia(phone, body) {
  const open = phone.open_thread;
  if (!open || !Array.isArray(open.messages)) return phone;
  if (!open.messages.some((m) => m.id === body.message_id)) return phone;
  const messages = open.messages.map((m) => {
    if (m.id !== body.message_id) return m;
    const media = {
      ...(m.media || {}),
      mid: body.mid || (m.media && m.media.mid) || "",
      kind: body.kind || (m.media && m.media.kind) || "",
      url: body.url || "",
      poster_url: body.poster_url || "",
      status: body.url ? "ready" : "fallback",
    };
    return { ...m, media };
  });
  return { ...phone, open_thread: { ...open, messages } };
}

/**
 * Whether the phone is in the player's hand (v0.23.0 spec §8.2, §14.1): `phone.world.phone_up`. A payload with no
 * `world` section (a block older than v0.23.0) is a phone that is up, as v0.22.0 played it.
 */
export function phoneUpOf(phone) {
  const world = phone && phone.world;
  return world && typeof world.phone_up === "boolean" ? world.phone_up : true;
}

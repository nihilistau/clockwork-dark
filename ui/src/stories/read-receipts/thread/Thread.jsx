/**
 * A conversation, on any app (spec §18.2's thread): bubbles with their
 * times, the read state of the player's last message ("Read 21:16" on an app
 * with receipts, "Delivered" elsewhere), typing dots only while the thread
 * row says `typing`, "…" for a message not yet voiced, photo / voice / video
 * tiles, the engine's own lines, open requests with their answers, the games
 * with this person, "Load earlier" paging the archive, and the
 * compose bar with the app's own attachments.
 *
 * The messages are the payload's `open_thread` (the thread the player last
 * opened, with later pushes applied: state.js `currentPhone`). Opening a
 * thread is an action (`open_thread`, spec §7.1), so until its answer comes
 * the thread shows only its row. Older pages come from `GET
 * /api/phone/thread/<id>?before=&limit=50` (newest first; kept here, oldest
 * first, until another thread opens).
 *
 * Only what the payload shows is drawn: closeness is the row's `stage_words`,
 * never a number; nothing hidden (warmth, interest, ghosted, a game's other
 * rack, a meet-up's flake) is in the payload to draw.
 */
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";

import Avatar from "../phone/Avatar.jsx";
import { appOf, threadOf } from "../phone/apps.js";
import { stampOf } from "../phone/format.js";
import Bubble from "./Bubble.jsx";
import ComposeBar from "./ComposeBar.jsx";
import RequestCard, { GameCard } from "./RequestCard.jsx";
import SystemLine from "./SystemLine.jsx";
import TypingDots from "./TypingDots.jsx";

export { TEXT_MAX } from "./ComposeBar.jsx";

/** The places a plan may name: the `meet_options` venues (with their words), else the Places app's list. */
export function venuesOf(phone) {
  const options = phone.meet_options && Array.isArray(phone.meet_options.venues) ? phone.meet_options.venues : null;
  const list = options && options.length ? options : (phone.places && phone.places.venues) || [];
  return list.map((v) => ({ id: v.id, label: v.place || v.label || v.id }));
}

/** One page of an older thread (`limit` 50, the route's own cap). */
export const PAGE_SIZE = 50;

/** The page route (engine/social/routes.py `api_phone_thread`): resolves `{messages, more}`, throws on failure. */
export async function fetchThreadPage(sessionId, threadId, before, limit = PAGE_SIZE) {
  const query = new URLSearchParams({ session_id: sessionId || "", before: before || "", limit: String(limit) });
  const res = await fetch(`/api/phone/thread/${encodeURIComponent(threadId)}?${query.toString()}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.busy ? "busy" : data.error || `server said ${res.status}`);
  return data;
}

/** A game this recent (in-game hours) still shows in the thread once it is over. */
const RECENT_HOURS = 24;

const hoursOf = (now) => (now ? (Number(now.day) - 1) * 24 + Number(now.hour) + Number(now.minute || 0) / 60 : 0);

function Message({ m, now, name }) {
  if (m.kind === "system" || m.kind === "recap" || m.kind === "request") {
    return <SystemLine m={m} name={name} />;
  }
  return <Bubble m={m} now={now} />;
}

export default function Thread({
  phone,
  threadId,
  act,
  pending = null,
  notSent = null,
  onRetry = null,
  onClearNotSent = () => {},
  onBack,
  sessionId = "",
  onOpenGame = null,
  onOpenContact = null,
  fetchPage = fetchThreadPage,
}) {
  const row = threadOf(phone, threadId);
  const open = phone.open_thread && phone.open_thread.thread_id === threadId ? phone.open_thread : null;
  const messages = open ? open.messages || [] : [];
  const lost = notSent && notSent.action === "send" && notSent.target === threadId ? notSent : null;
  const [earlier, setEarlier] = useState({ thread: threadId, rows: [], more: null, loading: false, error: "" });
  const list = useRef(null);
  const input = useRef(null);
  const keepFrom = useRef(null);
  const shownThread = useRef(threadId);
  shownThread.current = threadId;

  // Another thread: its own pages.
  if (earlier.thread !== threadId) setEarlier({ thread: threadId, rows: [], more: null, loading: false, error: "" });

  useEffect(() => {
    const el = list.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, row?.typing]);

  // An older page went in above: hold the reader where they were.
  useLayoutEffect(() => {
    const el = list.current;
    if (el && keepFrom.current != null) {
      el.scrollTop = el.scrollHeight - keepFrom.current;
      keepFrom.current = null;
    }
  }, [earlier.rows.length]);

  const name = row?.name || open?.name || "";
  const app = appOf(phone, row?.app || open?.app || "");
  const closed = (row && row.open === false) || (open && open.open === false);
  const shownIds = new Set(messages.map((m) => m.id));
  const timeline = [...earlier.rows.filter((m) => !shownIds.has(m.id)), ...messages];
  const last = [...messages].reverse().find((m) => m.from === "player" && m.kind !== "request");
  const sending = Boolean(pending && pending.action === "send" && pending.target === threadId);
  const more = earlier.more == null ? Boolean(open && open.more) : earlier.more;
  const typing = row ? Boolean(row.typing) : Boolean(open && open.typing);

  // Their newest message, as the status line speaks it (only what has arrived: never an earlier page).
  const newest = [...messages].reverse().find((m) => m.from !== "player" && m.kind !== "system" && m.kind !== "recap");
  const heard = !newest
    ? ""
    : newest.pending
      ? ""
      : newest.bubbles && newest.bubbles.length
        ? `${name}: ${newest.bubbles.join(" ")}`
        : newest.kind === "photo" || newest.kind === "voice" || newest.kind === "video"
          ? `${name} sent ${newest.kind === "photo" ? "a photo" : newest.kind === "voice" ? "a voice note" : "a video"}`
          : "";

  const pid = row?.pid || open?.pid || "";
  // What they have told the player of their days (the `hints` section: the engine's words, never a number).
  const hint = (phone.hints && phone.hints[pid]) || null;
  const available = hint && typeof hint.available_words === "string" ? hint.available_words : "";
  const now = phone.now;
  const nowHours = hoursOf(now);
  const requests = (phone.requests || []).filter(
    (r) => (r.thread_id === threadId || (!r.thread_id && r.pid === pid)) && (r.status === "pending" || r.status === "later")
  );
  const games = (phone.games || []).filter(
    (g) => g.pid === pid && (g.status === "active" || (g.ended_at != null && nowHours - Number(g.ended_at) <= RECENT_HOURS))
  );

  const loadEarlier = async () => {
    if (earlier.loading) return;
    const before = timeline.length ? timeline[0].id : "";
    setEarlier((e) => ({ ...e, loading: true, error: "" }));
    try {
      const page = await fetchPage(sessionId, threadId, before, PAGE_SIZE);
      const older = (Array.isArray(page && page.messages) ? page.messages : []).slice().reverse();
      // A page that lands after another thread opened changes nothing (review M6).
      if (shownThread.current !== threadId) return;
      const el = list.current;
      keepFrom.current = el ? el.scrollHeight - el.scrollTop : null;
      setEarlier((e) => {
        if (e.thread !== threadId) return e;
        const have = new Set(e.rows.map((m) => m.id));
        return { ...e, rows: [...older.filter((m) => m && m.id && !have.has(m.id)), ...e.rows], more: Boolean(page && page.more), loading: false };
      });
    } catch (err) {
      setEarlier((e) =>
        e.thread !== threadId
          ? e
          : { ...e, loading: false, error: err && err.message === "busy" ? "The phone is busy. Try again in a moment." : "Couldn't load earlier messages." }
      );
    }
  };

  const onSend = (intent) => {
    if (lost) {
      onClearNotSent();
      if (onRetry) return onRetry(intent);
    }
    // What the sender answered: the compose bar plays its send sound only for an action that went (spec §9.7).
    return act(intent);
  };

  return (
    <section className="rr-thread" aria-label={`Chat with ${name}`}>
      <header className="rr-thread__head">
        <button type="button" className="rr-back" aria-label="Back" onClick={onBack}>
          <span aria-hidden="true">‹</span>
        </button>
        <Avatar pid={pid} name={name} url={row?.avatar_url} size="sm" />
        <span className="rr-thread__who">
          <span className="rr-thread__name" tabIndex={-1}>
            {name}
          </span>
          {row?.stage_words && <span className="rr-thread__stage">{row.stage_words}</span>}
          {available && (
            <span className="rr-thread__avail" data-testid="thread-available">
              {available}
            </span>
          )}
        </span>
        {onOpenContact && pid && (
          <button type="button" className="rr-thread__info" aria-label={`About ${name}`} onClick={() => onOpenContact(pid)}>
            <span aria-hidden="true">i</span>
          </button>
        )}
      </header>
      {/* The list is not a live region: "Load earlier" puts up to 50 rows in at once (review M5).
          What arrives is spoken by the one status line below: their newest message. */}
      <p className="visually-hidden" role="status" aria-live="polite" data-testid="thread-announce">
        {heard}
      </p>
      <ol className="rr-thread__list" ref={list} aria-busy={earlier.loading || undefined}>
        {open && more && (
          <li className="rr-thread__earlier">
            <button type="button" className="rr-btn rr-btn--small rr-btn--quiet" disabled={earlier.loading} onClick={loadEarlier}>
              {earlier.loading ? "Loading…" : "Load earlier"}
            </button>
            {earlier.error && <span className="rr-card__sub" role="status">{earlier.error}</span>}
          </li>
        )}
        {!open && <li className="rr-msg rr-msg--system">Opening…</li>}
        {open && timeline.length === 0 && <li className="rr-msg rr-msg--system">You matched with {name}. Say hello.</li>}
        {timeline.map((m) => (
          <Message key={m.id} m={m} now={now} name={name} />
        ))}
        {last && row?.read_state && (
          <li className="rr-msg__read" data-testid="read-state">
            {row.read_state === "read" ? `Read ${last.read_at != null ? stampOf(last.read_at, now) : ""}`.trim() : "Delivered"}
          </li>
        )}
        {games.map((g) => (
          <GameCard key={g.id} game={g} onOpenGame={onOpenGame} />
        ))}
        {requests.map((r) => (
          <RequestCard key={r.id} request={r} name={name} now={now} act={act} pending={pending} />
        ))}
        {typing && <TypingDots name={name} threadId={threadId} lastAt={row && row.last ? row.last.at : ""} />}
      </ol>
      {closed ? (
        <p className="rr-thread__closed">This conversation has ended.</p>
      ) : (
        <ComposeBar
          threadId={threadId}
          app={app}
          player={phone.player || {}}
          sessionId={sessionId}
          act={act}
          sending={sending}
          lost={lost}
          onSend={onSend}
          inputRef={input}
          readyAsks={row?.asks}
          pid={pid}
          venues={venuesOf(phone)}
          kinds={phone.meet_options && phone.meet_options.kinds}
          canSignOff={Boolean(row) && row.open !== false}
        />
      )}
    </section>
  );
}

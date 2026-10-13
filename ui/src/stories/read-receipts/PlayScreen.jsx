/**
 * READ RECEIPTS' whole play screen (spec §18.1-18.2): the phone.
 *
 * Navigation -- the lock screen, home, which app, which thread -- is this
 * component's own state, never a turn: core gives a plugin no dispatch, and
 * moving between apps costs no in-game time. The one exception is opening a
 * thread, which is also the `open_thread` action (it marks the thread read).
 * A contact card and a game screen are navigation too, each remembering the
 * screen it was opened from (`back`); at 1200px wide and over the contact
 * card is a side sheet beside the phone instead (spec §18.3, `sheet`).
 *
 * Every action goes through `usePhoneAct`: one at a time from the deck's
 * point of view, and an action that never went comes back with what the
 * player wrote. The `busy` prop is ignored on purpose (spec §18.2): a rejoin's
 * `turn_running` reflects a snapshot or a commit holding the turn lock for
 * milliseconds, and would only grey out a phone that is not waiting on it.
 */
import React, { useEffect, useRef, useState } from "react";

import FrontPorch from "./apps/FrontPorch.jsx";
import Matchstick from "./apps/Matchstick.jsx";
import ChatList, { threadsOf } from "./apps/ChatList.jsx";
import Messenger, { NotYet } from "./apps/Messenger.jsx";
import Calendar from "./calendar/Calendar.jsx";
import ContactCard from "./contact/ContactCard.jsx";
import Contacts from "./contact/Contacts.jsx";
import GamesHome from "./games/GamesHome.jsx";
import ThisOrThat from "./games/ThisOrThat.jsx";
import TileTalk from "./games/TileTalk.jsx";
import Photos from "./photos/Photos.jsx";
import Settings from "./settings/Settings.jsx";
import { useIdleWait, useLetTimePassPref, watching } from "./settings/letTimePass.js";
import { appOf, threadOf } from "./phone/apps.js";
import Frame from "./phone/Frame.jsx";
import Home from "./phone/Home.jsx";
import LockScreen from "./phone/LockScreen.jsx";
import StatusBar from "./phone/StatusBar.jsx";
import { usePhoneAct } from "./phone/usePhoneAct.js";
import { currentPhone, initialState } from "./state.js";
import Thread from "./thread/Thread.jsx";

const TITLE = "Read Receipts";

/**
 * The landscape phone (spec §18.3, 844x390): no bezel, and above 700px wide
 * an open thread sits beside its app's conversation list. Under 900px wide
 * the frame has no bezel (theme/read-receipts.css), so only a landscape
 * screen between the two splits.
 */
export const SPLIT_QUERY = "(min-width: 701px) and (max-width: 899.98px) and (orientation: landscape)";

/** At 1200px wide and over the open contact card is a side sheet beside the phone (spec §18.3). */
export const SHEET_QUERY = "(min-width: 1200px)";

/** Whether a media query matches now, following it as the window changes; false with no matchMedia. */
function useMedia(query) {
  const read = () => {
    try {
      return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(query).matches;
    } catch {
      return false;
    }
  };
  const [matches, setMatches] = useState(read);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return undefined;
    const list = window.matchMedia(query);
    const on = () => setMatches(list.matches);
    on();
    list.addEventListener?.("change", on);
    return () => list.removeEventListener?.("change", on);
  }, [query]);
  return matches;
}

/** Where a run opens: the lock screen. */
const LOCKED = { at: "lock", app: "", thread: "" };

function Refusal({ refusal, onDismiss }) {
  return (
    <div className="rr-toast" role="status">
      <span>{refusal.reason}</span>
      <button type="button" className="rr-toast__close" aria-label="Dismiss" onClick={onDismiss}>
        <span aria-hidden="true">×</span>
      </button>
    </div>
  );
}

export default function PlayScreen({ state, sessionId = "", onAct, onOpenMenu, onOpenSaves, blocked = false }) {
  const story = state.story || initialState;
  const phone = currentPhone(state);
  const { act, pending, notSent, clearNotSent, retry } = usePhoneAct(onAct, story);
  const [nav, setNav] = useState(LOCKED);
  const [toast, setToast] = useState(null);
  const [sheet, setSheet] = useState(""); // the pid whose contact card is the side sheet (wide screens)
  const split = useMedia(SPLIT_QUERY);
  const wide = useMedia(SHEET_QUERY);
  const [letPass, setLetPass] = useLetTimePassPref();

  // A run just opened (new, or resumed after time away): the lock screen.
  const lockSeen = useRef(story.lockSeq);
  useEffect(() => {
    if (story.lockSeq === lockSeen.current) return;
    lockSeen.current = story.lockSeq;
    setNav(LOCKED);
    setSheet("");
  }, [story.lockSeq]);

  // The window narrowed under the sheet's width: the card moves into the phone.
  useEffect(() => {
    if (wide || !sheet) return;
    setNav((n) => ({ at: "contact", pid: sheet, back: n }));
    setSheet("");
  }, [wide, sheet]);

  // Focus follows the screen (the button pressed has just unmounted, and
  // focus would fall to the page): a thread's compose box, else the new
  // screen's heading, else the view itself. Not on the first paint.
  const view = useRef(null);
  const drawn = useRef(false);
  useEffect(() => {
    if (!drawn.current) {
      drawn.current = true;
      return;
    }
    const root = view.current;
    if (!root) return;
    const target =
      (nav.at === "thread" && root.querySelector(".rr-compose__input")) ||
      root.querySelector(".rr-app__title, .rr-thread__name") ||
      root;
    target.focus?.();
  }, [nav.at, nav.app, nav.thread, nav.pid, nav.game]);

  // The side sheet: focus into it when it opens, back to what opened it when it closes (review M7:
  // the thread's "i", a contact row, a calendar entry), else the thread's "i", else the view.
  const sheetSeen = useRef("");
  const sheetOpener = useRef(null);
  useEffect(() => {
    const was = sheetSeen.current;
    sheetSeen.current = sheet;
    if (sheet === was) return;
    const root = view.current;
    if (!root) return;
    if (sheet) {
      root.ownerDocument.querySelector(".rr-side .rr-app__title")?.focus?.();
      return;
    }
    const opener = sheetOpener.current;
    sheetOpener.current = null;
    const back = opener && opener.isConnected && root.contains(opener) ? opener : root.querySelector(".rr-thread__info") || root;
    back.focus?.();
  }, [sheet]);

  // "Let time pass" (spec 15.1, local only): 30 s untouched on a live thread sends a 15-minute wait.
  const watchedRow = phone && nav.at === "thread" ? threadOf(phone, nav.thread) : null;
  useIdleWait({
    enabled: Boolean(phone && phone.auto_wait === true && letPass && !blocked && watching(watchedRow, phone && phone.open_thread)),
    pending,
    act,
    root: view,
    again: story.turnSeq,
  });

  // The engine's refusal of the last action, shown once per answer (rule 1).
  const refusal = phone && phone.refusal;
  useEffect(() => {
    setToast(refusal && refusal.reason ? refusal : null);
  }, [story.turnSeq, refusal && refusal.reason]);

  if (!phone) {
    return (
      <Frame title={TITLE} onOpenMenu={onOpenMenu} onOpenSaves={onOpenSaves}>
        <p className="rr-empty rr-empty--boot">The phone is waking up…</p>
      </Frame>
    );
  }

  const openApp = (app) => setNav({ at: "app", app, thread: "" });
  const openThread = (threadId) => {
    const row = threadOf(phone, threadId);
    setNav((n) => ({ at: "thread", app: row?.app || n.app, thread: threadId, from: n.at === "app" ? n.app : "" }));
    act({ action: "open_thread", target: threadId, args: {}, text: "" });
  };
  const goHome = () => setNav({ at: "home", app: "", thread: "" });
  const goBack = () => setNav((n) => n.back || { at: "home", app: "", thread: "" });
  const openContact = (pid) => {
    if (!wide) {
      setNav((n) => ({ at: "contact", pid, back: n }));
      return;
    }
    const active = view.current && view.current.ownerDocument.activeElement;
    if (!sheet && active && view.current.contains(active)) sheetOpener.current = active;
    setSheet(pid);
  };
  const openGame = (id) => setNav((n) => ({ at: "game", game: id, back: n.at === "game" ? n.back : n }));
  const contactOf = (pid) => (phone.contacts || []).find((c) => c.pid === pid) || null;
  // The chat a game links to: their latest listed thread (the threads come latest first).
  const chatOf = (pid) => (phone.threads || []).find((t) => t.pid === pid) || null;

  const shared = { phone, act, pending, notSent, blocked, onRetry: (intent) => act(intent), onClearNotSent: clearNotSent, onOpenThread: openThread };

  let body;
  if (nav.at === "lock") {
    body = <LockScreen phone={phone} lock={story.lock} act={act} pending={pending} onUnlock={goHome} onOpenThread={openThread} />;
  } else if (nav.at === "home") {
    body = <Home phone={phone} onOpenApp={openApp} />;
  } else if (nav.at === "thread") {
    const thread = (
      <Thread
        {...shared}
        threadId={nav.thread}
        sessionId={sessionId || state.sessionId || ""}
        onOpenGame={openGame}
        onOpenContact={openContact}
        onBack={() => (nav.from ? openApp(nav.from) : nav.app ? openApp(nav.app) : goHome())}
      />
    );
    body = split ? (
      <div className="rr-split" data-testid="thread-split">
        <aside className="rr-split__list" aria-label="Conversations">
          <ChatList rows={threadsOf(phone, nav.app)} now={phone.now} onOpenThread={openThread} empty="No other conversations." current={nav.thread} />
        </aside>
        {thread}
      </div>
    ) : (
      thread
    );
  } else if (nav.at === "contact") {
    body = (
      <ContactCard contact={contactOf(nav.pid)} phone={phone} act={act} pending={pending} onBack={goBack} onOpenThread={openThread} />
    );
  } else if (nav.at === "game") {
    const game = (phone.games || []).find((g) => g.id === nav.game) || null;
    const props = { game, act, pending, chat: game ? chatOf(game.pid) : null, onOpenChat: openThread, onBack: goBack };
    body = !game ? <NotYet label="That game" /> : game.game === "this_or_that" ? <ThisOrThat {...props} /> : <TileTalk {...props} />;
  } else if (nav.app === "matchstick") {
    body = <Matchstick {...shared} />;
  } else if (nav.app === "front_porch") {
    body = <FrontPorch {...shared} />;
  } else {
    const app = appOf(phone, nav.app);
    const label = app ? app.label : nav.app;
    const kind = app ? app.kind : "";
    if (kind === "messenger") body = <Messenger phone={phone} app={nav.app} label={label} onOpenThread={openThread} />;
    else if (kind === "games") body = <GamesHome phone={phone} act={act} pending={pending} onOpenGame={openGame} />;
    else if (kind === "gallery") body = <Photos phone={phone} onOpenThread={openThread} />;
    else if (kind === "calendar") body = <Calendar phone={phone} act={act} pending={pending} onOpenContact={openContact} />;
    else if (kind === "contacts") body = <Contacts phone={phone} onOpenContact={openContact} />;
    else if (kind === "settings")
      body = <Settings phone={phone} act={act} pending={pending} letTimePass={letPass} onLetTimePass={setLetPass} />;
    else body = <NotYet label={label} />;
  }

  // A lost action the open screen does not keep itself (a swipe, a wait): one line to send it again.
  const keptHere =
    notSent &&
    ((nav.at === "thread" && notSent.action === "send" && notSent.target === nav.thread) ||
      (nav.at === "app" && nav.app === "front_porch" && (notSent.action === "like" || notSent.action === "like_back")));

  const side =
    wide && sheet ? (
      <ContactCard
        key={sheet}
        contact={contactOf(sheet)}
        phone={phone}
        act={act}
        pending={pending}
        onBack={() => setSheet("")}
        onOpenThread={openThread}
        sheet
      />
    ) : null;

  return (
    <Frame title={TITLE} onOpenMenu={onOpenMenu} onOpenSaves={onOpenSaves} side={side}>
      <StatusBar
        now={phone.now}
        onOpenMenu={onOpenMenu}
        onLock={
          nav.at === "lock"
            ? null
            : () => {
                setNav(LOCKED);
                setSheet("");
              }
        }
        wall={nav.at === "lock" || nav.at === "home"}
      />
      <div className={`rr-view rr-view--${nav.at}`} ref={view} tabIndex={-1}>
        {body}
      </div>
      {toast && <Refusal refusal={toast} onDismiss={() => setToast(null)} />}
      {notSent && !keptHere && (
        <button type="button" className="rr-notsent rr-notsent--float" onClick={retry}>
          Not sent — tap to retry
        </button>
      )}
      {nav.at !== "lock" && (
        <nav className="rr-homebar">
          <button type="button" className="rr-homebar__btn" aria-label="Home" onClick={goHome}>
            <span aria-hidden="true" />
          </button>
        </nav>
      )}
    </Frame>
  );
}

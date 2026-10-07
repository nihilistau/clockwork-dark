/**
 * The connection, as one state machine (v0.21.0, spec §6.3).
 *
 * WHY. Socket.IO does not retry after the SERVER closes a socket ("io server
 * disconnect", hosted mode's SocketDoor.drop) or refuses its connect (a
 * CONNECT_ERROR destroys the socket); the old client then read
 * "Reconnecting…" forever (F3). It also RESUMED on every connect, rebuilding
 * a live session under its own id (F4: the two-tabs mechanism), and left
 * every control live while disconnected, so Socket.IO buffered the press and
 * sent it to a room the new socket was not in (F5).
 *
 * THE RULES. Never resume while the session may be live: only the join's
 * exact miss resumes (transition 18); the join timer re-joins, never resumes.
 * Never re-enable controls over a turn still running (17, 22-24) or dropped
 * (16's unanswered check). Every emit here is skipped unless
 * `socket.connected` (no buffered emit, B3). A dead hosted login goes to "/"
 * at most twice a minute (the bounce guard), then says so and stops.
 *
 * REFS, NOT CLOSURES. The handlers are registered once; they read
 * `refs.session.current` and friends, kept current by App, never `state.*`.
 *
 * ORDER. App calls `connect(dispatch)` (socket.js) BEFORE this, so for every
 * server event the store reduces socket.js's SOCKET action first and this
 * machine's LINK second: a rejoin's `game_started` is reduced while the link
 * still reads `rejoining` (store.js, reduceRejoin).
 *
 * The transition numbers in the comments are the spec's table; one vitest
 * case per row (ui/tests/connection.test.js). Rows 29-32 are hosted mode's
 * `session_ended` and this tab's own Begin/Load (`leaving`, `join`): a run
 * released under this tab says why and is never resumed automatically, and
 * the run this tab just began or loaded goes live on its own answer.
 */

export const LINK = Object.freeze({
  CONNECTING: "connecting",
  LIVE: "live",
  REJOINING: "rejoining",
  AWAITING: "awaiting",
  RESUMING: "resuming",
  RESUME_REFUSED: "resume_refused",
  REFUSED: "refused",
  RETRYING: "retrying",
  OFFLINE: "offline",
  SIGNED_OUT: "signed_out",
  AUTH_STUCK: "auth_stuck",
  ELSEWHERE: "elsewhere",
  ENDED: "ended",
});

// Plan decision 7: `refused` is not connected either.
const NOT_CONNECTED = new Set(["connecting", "retrying", "offline", "signed_out", "auth_stuck", "refused"]);

export function isConnected(link) {
  return !NOT_CONNECTED.has(link);
}

export const PROBE_URL = "/api/games/active";
export const BOUNCE_KEY = "clockwork_auth_bounce";
export const BOUNCE_WINDOW_MS = 60000;
export const BOUNCE_LIMIT = 2;
export const SIGNOUT_DELAY_MS = 1500;
export const PROBE_EVERY_MS = 10000;
export const JOIN_WAITS_MS = [8000, 16000, 30000];
// Not to be shortened or removed: a join can land after its turn's
// `turn_update` went out but before the turn lock is released, and then this
// poll is the only thing that ends `awaiting` (spec §6.3).
export const AWAIT_POLL_MS = 15000;
export const BACKOFF_MS = [1000, 2000, 4000, 8000, 15000];
export const OFFLINE_AFTER = 5;

const WORDS = {
  rejoining: "Reconnected — picking up your run…",
  awaiting: "Your move is still being played…",
  resuming: "Opening your run…",
  resume_refused: "Your run could not be opened.",
  refused: "The server refused the connection.",
  retrying: "Connection lost.",
  offline: "The server is not answering.",
  signed_out: "Your login has ended. Taking you to sign in…",
  auth_stuck: "We could not confirm your login.",
  elsewhere: "This run is open in another window.",
  ended: "This session was ended. Your run is saved.",
  reconnected: "Reconnected.",
  lost: "That run is no longer open.",
  unanswered: "Your move was not answered.",
  unanswered_lost: "Your move was not answered, and it is no longer on offer. Choose again.",
};

const ACTIONS = {
  retrying: "try",
  offline: "try",
  refused: "try",
  resume_refused: "resume",
  ended: "resume",
  lost: "resume",
  elsewhere: "play",
  auth_stuck: "signin",
  unanswered: "again",
};

/** A banner: its words are constant for its kind; a countdown rides `retryAt` (Review 22). */
export function banner(kind, extra = {}) {
  return {
    kind,
    text: WORDS[kind] || "",
    action: ACTIONS[kind] || null,
    role: kind === "signed_out" || kind === "auth_stuck" ? "alert" : "status",
    retryAt: null,
    detail: "",
    ...extra,
  };
}

function sessionStore() {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function createLink({ socket, dispatch, refs, env = {} }) {
  const fetchImpl = env.fetch || ((url, init) => fetch(url, init));
  const assign = env.assign || ((url) => window.location.assign(url));
  const storage = env.storage === undefined ? sessionStore() : env.storage;
  const now = env.now || (() => Date.now());
  const random = env.random || Math.random;

  let link = LINK.CONNECTING;
  let attempts = 0;
  let step = 0;
  let joinWait = 0;
  let lastProbe = -Infinity;
  let recovering = false;
  // 32: the run this tab just began or loaded (`join`), until its answer.
  let pending = "";
  // `leaving` took the link out of a rejoin/await of the run it left; a
  // refused Begin/Load (`stay`) puts the rejoin back.
  let leftRecovery = false;
  // Connects so far, so `stay` can tell a reconnect that came while the
  // Begin/Load was out (it found no run to rejoin, so `stay` rejoins).
  let connects = 0;
  let leftAt = 0;
  // Play here / Resume pressed while the socket was down: sent on the connect.
  let resumeOnConnect = false;
  let stopped = false;
  // The banner on screen, so a transport error in `refused` keeps the
  // server's own words rather than replacing them (review 8).
  let shownBanner = null;
  const timers = { retry: null, join: null, await: null, signout: null };

  function set(next, shown = null, extra = {}) {
    link = next;
    shownBanner = shown;
    refs.link.current = next;
    dispatch({ type: "LINK", link: next, banner: shown, ...extra });
  }
  function clear(name) {
    if (timers[name] !== null) {
      clearTimeout(timers[name]);
      timers[name] = null;
    }
  }
  function clearAll() {
    for (const name of Object.keys(timers)) clear(name);
  }
  function emit(event, payload) {
    if (socket.connected) socket.emit(event, payload);
  }
  // This tab's save, falling back to the browser's last one only when the
  // tab has none (App: `saveRef || loadSaveId`, T12 fix round 1): the
  // shared one may be another tab's run.
  const storedSave = () => refs.save() || "";
  const noRunLeft = () => refs.outgoing.current.size === 0;

  // -- the bounce guard (§6.4) --------------------------------------------
  function bounces() {
    try {
      const list = JSON.parse(storage?.getItem(BOUNCE_KEY) || "[]");
      return Array.isArray(list) ? list.filter(Number.isFinite) : [];
    } catch {
      return [];
    }
  }
  function writeBounces(list) {
    try {
      storage?.setItem(BOUNCE_KEY, JSON.stringify(list));
    } catch {
      /* no storage: the guard degrades to "navigate", which is what a page reload would do */
    }
  }
  function clearBounces() {
    try {
      storage?.removeItem(BOUNCE_KEY);
    } catch {
      /* ignore */
    }
  }

  /** Reaching `live`: the one place timers stop, the backoff resets and the bounce list clears. */
  function goLive(extra = {}) {
    clear("retry");
    clear("join");
    clear("await");
    attempts = 0;
    step = 0;
    clearBounces();
    const shown = recovering ? banner("reconnected") : null;
    recovering = false;
    set(LINK.LIVE, shown, extra);
  }

  function nextDelay() {
    const base = BACKOFF_MS[Math.min(step, BACKOFF_MS.length - 1)];
    step += 1;
    return Math.round(base * (0.8 + 0.4 * random()));
  }

  /** The client's own reconnect, for when Socket.IO will not retry. Returns when it fires. */
  function scheduleConnect() {
    clear("retry");
    const ms = nextDelay();
    timers.retry = setTimeout(() => {
      timers.retry = null;
      if (stopped) return;
      attempts += 1;
      if (attempts >= OFFLINE_AFTER && link === LINK.RETRYING) set(LINK.OFFLINE, banner("offline"));
      socket.connect();
    }, ms);
    return now() + ms;
  }
  // Plan decision 13: a countdown only for a retry this client scheduled.
  const ownRetry = () => (socket.active ? null : scheduleConnect());

  function startJoinTimer() {
    clear("join");
    const ms = JOIN_WAITS_MS[Math.min(joinWait, JOIN_WAITS_MS.length - 1)];
    joinWait += 1;
    timers.join = setTimeout(onJoinTimer, ms);
  }

  function rejoin() {
    emit("join_session", { session_id: refs.session.current });
    joinWait = 0;
    startJoinTimer();
    set(LINK.REJOINING, banner("rejoining"));
  }

  function sendResume() {
    const save = storedSave();
    if (!save) return false;
    emit("resume", { save_id: save });
    set(LINK.RESUMING, banner("resuming"));
    return true;
  }

  // -- the auth probe (§6.4) ----------------------------------------------
  async function probe(force = false) {
    const t = now();
    if (!force && t - lastProbe < PROBE_EVERY_MS) return;
    lastProbe = t;
    let response;
    try {
      response = await fetchImpl(PROBE_URL, { cache: "no-store", credentials: "same-origin" });
    } catch {
      return; // 12: a network error says nothing about the login
    }
    if (stopped) return;
    let body = {};
    try {
      body = (await response.json()) || {};
    } catch {
      body = {};
    }
    const status = Number(response.status);
    const loginGone =
      status === 401 || status === 409 || (status === 403 && String(body.error || "") === "password change required");
    if (loginGone) {
      signOut(); // 9, 10, 38
      return;
    }
    if (status === 503 && (link === LINK.RETRYING || link === LINK.OFFLINE)) {
      set(link, banner(link, { detail: String(body.error || "") })); // 11
      return;
    }
    if (status === 429 && body.error) {
      // Hosted: the account is at its connection cap. The front door refuses
      // the WebSocket upgrade with a 429 the browser cannot read (a transport
      // error here), so its words come through the probe (T11 fix round 1).
      const words = String(body.error);
      if ((link === LINK.RETRYING || link === LINK.OFFLINE) && !refs.session.current) {
        // A page with no run on screen: the cap is the whole story (37's state).
        set(LINK.REFUSED, banner("refused", { text: words, retryAt: ownRetry() }));
      } else if (link === LINK.RETRYING || link === LINK.OFFLINE) {
        // A run to rejoin: stay where the rejoin rules apply, and say why.
        set(link, banner(link, { detail: words, retryAt: shownBanner?.retryAt ?? null }));
      } else if (link === LINK.REFUSED) {
        set(LINK.REFUSED, banner("refused", { text: words, retryAt: shownBanner?.retryAt ?? null }));
      }
    }
    // 12, 39: a good login -- nothing changes, and never a navigation.
  }

  function signOut() {
    if (link === LINK.SIGNED_OUT || link === LINK.AUTH_STUCK) return;
    const recent = bounces().filter((at) => now() - at < BOUNCE_WINDOW_MS);
    clearAll();
    if (recent.length >= BOUNCE_LIMIT) {
      // 10: the door admits the page and refuses its socket. Two reloads, then a sentence and a link.
      stopped = true;
      set(LINK.AUTH_STUCK, banner("auth_stuck"));
      socket.disconnect();
      return;
    }
    writeBounces([...recent, now()]); // 9
    set(LINK.SIGNED_OUT, banner("signed_out"));
    timers.signout = setTimeout(() => assign("/"), SIGNOUT_DELAY_MS);
  }

  // -- socket events ------------------------------------------------------
  function onConnect() {
    if (stopped) return;
    connects += 1;
    clear("retry");
    attempts = 0;
    step = 0;
    if (pending && !refs.session.current) {
      // 32: this tab began or loaded a run while the socket was down, so its
      // join was never sent. Join it now; its own answer goes live, and a
      // miss resumes through 18 (T12 fix round 1).
      refs.session.current = pending;
      recovering = true;
      rejoin();
      return;
    }
    if (resumeOnConnect) {
      resumeOnConnect = false;
      if ([LINK.RESUME_REFUSED, LINK.ENDED, LINK.ELSEWHERE].includes(link) && sendResume()) return; // 28, pressed while down
    }
    if (link === LINK.CONNECTING || link === LINK.REFUSED) {
      if (storedSave() && noRunLeft() && sendResume()) return; // 2, 40
      goLive(); // 1, 40
      return;
    }
    if (link === LINK.RETRYING || link === LINK.OFFLINE) {
      recovering = true;
      if (refs.session.current) {
        rejoin(); // 13
        return;
      }
      if (storedSave() && noRunLeft() && sendResume()) return; // 14
      goLive(); // 15
    }
  }

  function onDisconnect(reason) {
    if (reason === "io client disconnect") return; // 3
    if (![LINK.LIVE, LINK.AWAITING, LINK.REJOINING, LINK.RESUMING].includes(link)) return;
    refs.busyAtDrop.current = Boolean(refs.busy.current); // 4
    clear("join");
    clear("await");
    set(LINK.RETRYING, banner("retrying", { retryAt: ownRetry() }));
  }

  function onReconnectAttempt(n) {
    if (stopped || link !== LINK.RETRYING) return;
    attempts = Number(n) || attempts + 1;
    if (attempts >= OFFLINE_AFTER) set(LINK.OFFLINE, banner("offline")); // 6 (else 5)
  }

  function onConnectError(err) {
    if (stopped) return;
    const refused = err?.type !== "TransportError"; // §6.1: the discriminator (Review 6)
    if (link === LINK.CONNECTING) {
      if (!refused) {
        set(LINK.RETRYING, banner("retrying")); // 36: Socket.IO's own retry runs
      } else {
        set(LINK.REFUSED, banner("refused", { text: err?.message || WORDS.refused, retryAt: ownRetry() })); // 37
      }
      probe(true);
      return;
    }
    if (link === LINK.REFUSED) {
      // Only a refusal rewrites the words; a transport error (the server
      // simply down after our own connect) keeps the banner's (review 8).
      const text = (refused && err?.message) || shownBanner?.text || WORDS.refused;
      set(LINK.REFUSED, banner("refused", { text, retryAt: ownRetry() }));
      probe();
      return;
    }
    if (link === LINK.RETRYING || link === LINK.OFFLINE) {
      if (refused) set(link, banner(link, { detail: err?.message || "", retryAt: ownRetry() })); // 8
      probe(); // 7, 8
    }
  }

  /** Take the answer's id as this tab's run (React's effect skips an unchanged id). */
  function adopt(payload) {
    const id = String(payload?.session_id || "");
    if (id) refs.session.current = id;
  }

  /** 32: the answer to this tab's own Begin/Load join, whatever the state. */
  function ownAnswer(id) {
    return Boolean(pending) && id === pending;
  }

  function onSessionEnded(payload) {
    const id = String(payload?.session_id || "");
    if (!id || id !== refs.session.current) return; // 30: a run this tab has left, or never had
    // 29: no automatic rejoin or resume after this -- the release IS the
    // server keeping one live run per account, and an automatic resume here
    // would release the other tab, whose own would release this one.
    refs.session.current = "";
    pending = "";
    recovering = false;
    refs.busyAtDrop.current = false;
    clearAll();
    const kind = payload.reason === "elsewhere" ? "elsewhere" : "ended";
    set(kind === "elsewhere" ? LINK.ELSEWHERE : LINK.ENDED, banner(kind));
  }

  function onGameStarted(payload) {
    const id = String(payload?.session_id || "");
    if (ownAnswer(id)) {
      pending = ""; // 32: the run this tab just began or loaded
      adopt(payload);
      recovering = false;
      goLive();
      return;
    }
    if (link === LINK.LIVE && id && id === refs.session.current && payload?.turn_running && !refs.busy.current) {
      // A late answer for this run (the reducer ignores it) says a turn is
      // running while this page is idle: ask again rather than trust a
      // snapshot that may be stale (re-review R1). A page with its own move
      // in flight ignores it: that move's answer is on its way.
      rejoin();
      return;
    }
    if (link !== LINK.REJOINING || id !== refs.session.current) return;
    clear("join");
    if (payload?.turn_running) {
      set(LINK.AWAITING, banner("awaiting")); // 17
      timers.await = setTimeout(onAwaitTimer, AWAIT_POLL_MS);
      return;
    }
    const unanswered = Boolean(refs.busyAtDrop.current); // 16
    refs.busyAtDrop.current = false;
    goLive({ checkUnanswered: unanswered });
  }

  function onGameResumed(payload) {
    const own = ownAnswer(String(payload?.session_id || ""));
    if (!own && link !== LINK.RESUMING) return;
    pending = "";
    // A resume may rebuild the SAME id (the save carries it), which React's
    // effect would not re-send: after 29 this tab's ref would stay empty.
    adopt(payload);
    // 25. After a recovery (the join's miss, 18, or 14) the move in flight at
    // the drop may have died with the old session: the reducer recorded
    // whether the log ended on it before the resume's line was appended
    // (`pendingAgain`), and offers Try again (spec §6.7).
    const unanswered = !own && recovering && Boolean(refs.busyAtDrop.current);
    refs.busyAtDrop.current = false;
    goLive(unanswered ? { checkUnanswered: true } : {}); // 25, 32
  }

  function onResumeFailed() {
    if (link !== LINK.RESUMING) return;
    recovering = false;
    goLive(); // 26: the reducer puts the start screen and its message up
  }

  function onError(payload) {
    if (String(payload?.error || "") === "login required") {
      probe(true); // 19: the disconnect that follows takes rule 4
      return;
    }
    // This tab's OWN join (32) missed while no run is on screen (T12
    // re-review R1): the run it began or loaded is gone. Forget it, or a
    // later reconnect would re-join it, miss, and resume the stored save --
    // the OLD run -- releasing another window's run in hosted mode.
    if (pending && !refs.session.current && String(payload?.message || "") === "session not found") {
      pending = "";
    }
    if (link === LINK.REJOINING && refs.session.current && String(payload?.message || "") === "session not found") {
      clear("join"); // 18: the join's own, exact miss -- the only resume on a rejoin
      if (refs.session.current === pending) pending = "";
      if (!sendResume()) goLive();
    }
    // 20: anything else is logged by the reducer and changes nothing here.
  }

  function onTurnUpdate() {
    if (link === LINK.AWAITING) goLive(); // 22
  }

  function onTurnError(payload) {
    if (link === LINK.AWAITING) {
      goLive(); // 23
      return;
    }
    if (link === LINK.RESUMING) {
      set(LINK.RESUME_REFUSED, banner("resume_refused", { text: String(payload?.message || WORDS.resume_refused) })); // 27
      return;
    }
    if (link === LINK.LIVE && payload?.fatal) {
      set(LINK.LIVE, banner("lost", { text: String(payload?.message || WORDS.lost) })); // 35
    }
  }

  function onJoinTimer() {
    timers.join = null;
    if (link !== LINK.REJOINING) return;
    emit("join_session", { session_id: refs.session.current }); // 21: re-join, never resume
    startJoinTimer();
  }

  function onAwaitTimer() {
    timers.await = null;
    if (link !== LINK.AWAITING || !socket.connected) return;
    rejoin(); // 24
  }

  socket.on("connect", onConnect);
  socket.on("disconnect", onDisconnect);
  socket.on("connect_error", onConnectError);
  socket.io?.on?.("reconnect_attempt", onReconnectAttempt);
  socket.on("game_started", onGameStarted);
  socket.on("game_resumed", onGameResumed);
  socket.on("resume_failed", onResumeFailed);
  socket.on("error", onError);
  socket.on("turn_update", onTurnUpdate);
  socket.on("turn_error", onTurnError);
  socket.on("session_ended", onSessionEnded);

  return {
    /** 33: Try now. */
    tryNow() {
      if ([LINK.RETRYING, LINK.OFFLINE, LINK.RESUME_REFUSED, LINK.REFUSED].includes(link)) {
        clear("retry");
        step = 0;
        // While the Manager is mid-backoff, socket.io-client 4.8's connect()
        // skips io.open(), so the press did nothing (review 3). A disconnect
        // first closes the Manager (no event: the socket is not connected)
        // and the connect opens it at once.
        if (socket.io?._reconnecting) socket.disconnect();
        socket.connect();
      }
    },
    /** 28 and 35: Resume / Play here. */
    resume() {
      if (![LINK.RESUME_REFUSED, LINK.ENDED, LINK.ELSEWHERE, LINK.LIVE].includes(link)) return;
      if (socket.connected) {
        sendResume();
        return;
      }
      if (link === LINK.LIVE) return;
      // The socket went down while the banner sat there (rule 4 ignores a
      // drop here): connect now, check the login, and send on the connect.
      resumeOnConnect = true;
      if (socket.io?._reconnecting) socket.disconnect();
      socket.connect();
      probe(true);
    },
    /** 31: Begin/Load, before the POST -- this tab leaves its run. */
    leaving() {
      const id = refs.session.current;
      if (id) refs.outgoing.current.add(id);
      refs.session.current = "";
      // A rejoin or await of the run being left must not run on: its join
      // timer would re-send an empty id and its miss (18) would resume the
      // OLD save over the run this Begin/Load is making.
      clear("join");
      clear("await");
      leftAt = connects;
      leftRecovery = link === LINK.REJOINING || link === LINK.AWAITING;
      if (leftRecovery) {
        recovering = false;
        set(LINK.LIVE, null);
      }
      return id;
    },
    /** 31, undone: the server refused the Begin/Load, so this tab keeps its run. */
    stay(id) {
      const kept = String(id || "");
      const wasRecovering = leftRecovery;
      leftRecovery = false;
      if (!kept) return;
      refs.outgoing.current.delete(kept);
      if (refs.session.current) return;
      refs.session.current = kept;
      // Back to the rejoin `leaving` stopped, or one a reconnect meanwhile
      // skipped (it found no run): this socket may not be in the run's room.
      if ((wasRecovering || connects !== leftAt) && link === LINK.LIVE && socket.connected) {
        recovering = true;
        rejoin();
      }
    },
    /** 32: join the run this tab just began or loaded. */
    join(sessionId) {
      leftRecovery = false;
      pending = String(sessionId || "");
      emit("join_session", { session_id: pending });
    },
    /** 34: Sign in again -- a plain link; the bounce guard does not apply to a press. */
    signIn() {
      assign("/");
    },
    probe,
    get state() {
      return link;
    },
    dispose() {
      stopped = true;
      clearAll();
      // The Manager is shared and cached: leave no disposed machine on it (review 7).
      socket.io?.off?.("reconnect_attempt", onReconnectAttempt);
    },
  };
}

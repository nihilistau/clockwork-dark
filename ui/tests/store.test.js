/**
 * The core reducer.
 *
 * Everything the old client kept in loose module variables lives here, and the
 * bugs this file guards are all the same species: a field that fails to clear.
 * A `busy` that survives a dropped socket disables every control forever. An
 * `error` that survives the retry tells the player the world is broken while it
 * is answering. A streamed draft that survives its own rejection leaves prose
 * on screen that the server refused to send.
 *
 * `tests/test_narration_control.py` already parses store.js as TEXT for one of
 * these. Text is what you use when you cannot run the thing; this runs it.
 */
import { describe, expect, it } from "vitest";

import { createStore, initialState, reducer, retryTarget } from "../src/core/store.js";

/** A turn payload with only what the case under test needs. */
const socket = (event, payload = {}) => ({ type: "SOCKET", event, payload });

const started = () =>
  reducer(
    initialState,
    socket("game_started", {
      session_id: "s1",
      save_id: "v1",
      state: { location_id: "the_grid", world_day: 1, meters: {} },
      opening: { narration: "Rain on wet asphalt.", choices: [{ id: "a", text: "Jack it" }] },
    })
  );

describe("a turn", () => {
  it("opens a run onto the play screen with its opening in the log", () => {
    const state = started();
    expect(state.screen).toBe("scene");
    expect(state.sessionId).toBe("s1");
    expect(state.saveId).toBe("v1");
    expect(state.log.map((e) => e.text)).toEqual(["Rain on wet asphalt."]);
    expect(state.choices).toHaveLength(1);
    expect(state.busy).toBe(false);
  });

  it("applies a turn_update: narration, choices, world and meters", () => {
    let state = reducer(started(), { type: "SUBMIT", text: "Jack the shard" });
    expect(state.busy).toBe(true);

    state = reducer(
      state,
      socket("turn_update", {
        narration: "Forty seconds. You are in all of them.",
        choices: [{ id: "b", text: "Ask Mira what it costs" }],
        state: {
          location_id: "the_grid",
          world_day: 2,
          meters: { heat: { name: "heat", label: "Heat", kind: "meter", band: "faint" } },
        },
        save_id: "v2",
      })
    );

    expect(state.busy).toBe(false);
    expect(state.log.map((e) => e.text)).toContain("Forty seconds. You are in all of them.");
    expect(state.choices[0].id).toBe("b");
    expect(state.world.world_day).toBe(2);
    expect(state.meters.heat.band).toBe("faint");
    expect(state.saveId).toBe("v2");
  });

  it("replaces a streamed draft with the server's authoritative narration", () => {
    // The evaluator retry does not stream: on a retried turn the text on screen
    // is the REJECTED draft, and the accepted narration arrives only in
    // turn_update. Keeping the buffer would leave prose up that the server
    // declined to send.
    let state = reducer(started(), { type: "SUBMIT", text: "go" });
    state = reducer(state, socket("narration_delta", { text: "a draft that was refus" }));
    expect(state.streamingId).toBeTruthy();

    state = reducer(state, socket("turn_update", { narration: "What actually happened." }));
    expect(state.streamingId).toBeNull();
    const texts = state.log.map((e) => e.text);
    expect(texts).toContain("What actually happened.");
    expect(texts).not.toContain("a draft that was refus");
  });

  it("drops a streamed entry that resolved to nothing", () => {
    let state = reducer(started(), { type: "SUBMIT", text: "go" });
    state = reducer(state, socket("narration_delta", { text: "  " }));
    const before = state.log.length;
    state = reducer(state, socket("turn_update", { narration: "" }));
    expect(state.log.length).toBeLessThan(before);
  });

  it("never renders one turn's prose twice, whatever ended the turn first", () => {
    // The F-13 shape, and the only way the reducer could still reach it.
    //
    // Three actions null `streamingId` without a turn_update -- a dropped
    // socket, a client-side ERROR (the watchdog fires at 330s, on turns that
    // are still running) and a server turn_error. Each used to leave the
    // half-streamed paragraph orphaned in the log; the authoritative narration
    // then arrived, found no `streamingId`, took the append branch, and printed
    // the same prose a second time underneath it.
    const PROSE = "The tavern comes into view, a low-slung building of heavy timber.";
    const ends = [
      { type: "DISCONNECTED" },
      { type: "ERROR", message: "The world has not answered." },
      socket("turn_error", { message: "no answer" }),
    ];

    for (const ending of ends) {
      let state = reducer(started(), { type: "SUBMIT", text: "go" });
      state = reducer(state, socket("narration_delta", { text: "The tavern comes into vi" }));
      expect(state.streamingId).toBeTruthy();

      state = reducer(state, ending);
      expect(state.streamingId).toBeNull();
      // The orphan goes with it, rather than waiting in the log for a twin.
      expect(state.log.map((e) => e.text)).not.toContain("The tavern comes into vi");

      state = reducer(state, socket("turn_update", { narration: PROSE }));
      const narrations = state.log.filter((e) => e.kind === "narration").map((e) => e.text);
      expect(narrations.filter((t) => t === PROSE)).toHaveLength(1);
      // And nothing partial survived alongside it.
      expect(narrations.some((t) => t !== PROSE && PROSE.startsWith(t))).toBe(false);
    }
  });

  it("ignores a turn_update that repeats the narration already on screen", () => {
    // A reconnect replays the last payload. The append branch has no other way
    // to tell a replay from a new paragraph.
    const PROSE = "You turn your back on the watchman and start walking.";
    let state = reducer(started(), { type: "SUBMIT", text: "go" });
    state = reducer(state, socket("turn_update", { narration: PROSE }));
    state = reducer(state, socket("turn_update", { narration: PROSE }));

    const narrations = state.log.filter((e) => e.kind === "narration").map((e) => e.text);
    expect(narrations.filter((t) => t === PROSE)).toHaveLength(1);
  });

  it("still appends the next turn when it happens to follow the same beat", () => {
    // The dedupe is exact-text and looks only at the last narration, so an
    // ordinary run of turns is untouched.
    let state = reducer(started(), socket("turn_update", { narration: "One." }));
    state = reducer(state, { type: "SUBMIT", text: "again" });
    state = reducer(state, socket("turn_update", { narration: "Two." }));
    expect(state.log.filter((e) => e.kind === "narration").map((e) => e.text)).toEqual([
      "Rain on wet asphalt.",
      "One.",
      "Two.",
    ]);
  });

  it("makes an ending stick once it arrives", () => {
    // A reconnect replaying the last payload must not take the ending screen
    // away again.
    let state = reducer(started(), socket("turn_update", { ending: { ending_id: "quiet_floor" } }));
    expect(state.ending.ending_id).toBe("quiet_floor");
    state = reducer(state, socket("turn_update", { narration: "an echo" }));
    expect(state.ending.ending_id).toBe("quiet_floor");
  });
});

describe("failure and recovery", () => {
  it("an ERROR stops the turn and says so", () => {
    let state = reducer(started(), { type: "SUBMIT", text: "go" });
    state = reducer(state, { type: "ERROR", message: "The world has not answered." });
    expect(state.error).toBe("The world has not answered.");
    expect(state.busy).toBe(false);
    expect(state.streamingId).toBeNull();
  });

  it("the retry clears the error and does NOT re-echo the player's line", () => {
    // App re-sends through `emit("")`: the player's line is already in the log
    // from the attempt that failed, and a retry is the same move tried again,
    // not a second thing they did. `append` ignoring empty text is what makes
    // that true, so it is asserted here rather than trusted.
    let state = reducer(started(), { type: "SUBMIT", text: "Jack the shard" });
    state = reducer(state, socket("turn_error", { message: "no answer" }));
    expect(state.error).toBe("no answer");

    const before = state.log.length;
    state = reducer(state, { type: "SUBMIT", text: "" });
    expect(state.error).toBe("");
    expect(state.busy).toBe(true);
    expect(state.log).toHaveLength(before);
  });

  it("a dropped socket releases the controls", () => {
    let state = reducer(started(), { type: "SUBMIT", text: "go" });
    state = reducer(state, { type: "DISCONNECTED" });
    expect(state.connected).toBe(false);
    expect(state.busy).toBe(false);
    expect(state.streamingId).toBeNull();
  });

  it("an unreachable model is reported on the turn that found it", () => {
    const state = reducer(started(), socket("turn_update", { llm_unavailable: true }));
    expect(state.error).toMatch(/unreachable/i);
  });

  it("names the model server, not one brand of it", () => {
    // v0.19.0 speaks to more than LM Studio; the outage line must not send a
    // player on another server looking for an app they never installed.
    const state = reducer(started(), socket("turn_update", { llm_unavailable: true }));
    expect(state.error).toContain("the model server");
    expect(state.error).not.toMatch(/LM Studio/);
  });
});

describe("RESET", () => {
  it("clears the previous run and keeps only what outlives it", () => {
    let state = started();
    state = reducer(state, { type: "SAVES", saves: [{ save_id: "v1" }] });
    state = reducer(state, socket("turn_update", { ending: { ending_id: "burned" } }));
    state = reducer(state, { type: "CONNECTED" });

    const fresh = reducer(state, { type: "RESET", storyInitial: { district: "grid" } });

    expect(fresh.log).toEqual([]);
    expect(fresh.choices).toEqual([]);
    expect(fresh.world).toBeNull();
    expect(fresh.ending).toBeNull();
    expect(fresh.sessionId).toBe("");
    // The socket and the save list belong to the client, not to the run.
    expect(fresh.connected).toBe(true);
    expect(fresh.saves).toHaveLength(1);
    // The plugin's own reset value, not the previous run's slice.
    expect(fresh.story).toEqual({ district: "grid" });
  });

  it("with no storyInitial the slice is empty, not undefined", () => {
    const fresh = reducer(started(), { type: "RESET" });
    expect(fresh.story).toEqual({});
  });
});

describe("createStore", () => {
  it("runs the plugin's reducer after core's, on the fresh core state", () => {
    const plugin = {
      initialState: { seen: 0 },
      reduce: (slice, action, next) =>
        action.type === "SOCKET" ? { seen: next.world?.world_day ?? 0 } : slice,
    };
    const { initial, reducer: composed } = createStore(plugin);
    expect(initial.story).toEqual({ seen: 0 });

    const next = composed(initial, socket("turn_update", { state: { world_day: 9 } }));
    // The plugin saw the ALREADY-REDUCED core state, not the previous one.
    expect(next.story.seen).toBe(9);
  });

  it("keeps state identity when the plugin returns its slice unchanged", () => {
    const plugin = { initialState: { a: 1 }, reduce: (slice) => slice };
    const { initial, reducer: composed } = createStore(plugin);
    const next = composed(initial, { type: "REASONING_TOGGLE" });
    expect(next.story).toBe(initial.story);
  });

  it("works with no plugin at all", () => {
    const { initial, reducer: composed } = createStore(undefined);
    expect(initial.story).toEqual({});
    expect(composed(initial, { type: "CONNECTED" }).connected).toBe(true);
  });
});

describe("contention is not failure", () => {
  const socket = (event, payload = {}) => ({ type: "SOCKET", event, payload });

  const started = () =>
    reducer(
      initialState,
      socket("game_started", {
        session_id: "s1",
        state: { world_day: 1 },
        opening: { narration: "You come out of the wood." },
      }),
    );

  it("a busy turn_error leaves the running turn's prose alone", () => {
    // The server rejects a second `player_choice` while one is in flight. That
    // is the GUARD working -- the first turn is still generating and still
    // streaming onto the screen. Treating it as a dead turn ran `closeStream`,
    // which deleted the in-flight entry, and cleared `busy`, which re-enabled
    // every control while the server was still working. One stray double-press
    // was enough, and so was a second tab on the same session.
    let state = reducer(started(), { type: "SUBMIT", text: "go" });
    state = reducer(state, socket("narration_delta", { text: "The tavern comes into vi" }));
    const streamingId = state.streamingId;
    expect(streamingId).toBeTruthy();

    state = reducer(
      state,
      socket("turn_error", { message: "A turn is already in progress.", busy: true }),
    );

    expect(state.streamingId).toBe(streamingId);
    expect(state.log.map((e) => e.text)).toContain("The tavern comes into vi");
    expect(state.busy).toBe(true);
    expect(state.error).toBe("A turn is already in progress.");
  });

  it("a real turn_error still tears the turn down", () => {
    // The guard against over-fixing the case above: an actual failure must
    // still clear `busy` and drop the orphaned draft.
    let state = reducer(started(), { type: "SUBMIT", text: "go" });
    state = reducer(state, socket("narration_delta", { text: "The tavern comes into vi" }));

    state = reducer(state, socket("turn_error", { message: "the turn broke" }));

    expect(state.streamingId).toBeNull();
    expect(state.busy).toBe(false);
    expect(state.log.map((e) => e.text)).not.toContain("The tavern comes into vi");
  });
});

describe("quest events reach the player", () => {
  const socket = (event, payload = {}) => ({ type: "SOCKET", event, payload });

  const started = () =>
    reducer(
      initialState,
      socket("game_started", {
        session_id: "s1",
        state: { world_day: 1 },
        opening: { narration: "You come out of the wood." },
      }),
    );

  it("appends a log entry for each quest event on the turn", () => {
    // The server has always carried `quest_events` -- started, advanced,
    // completed, failed -- and nothing in the client read the key. So a stage
    // that awards gold and an item paid out with no line on screen anywhere,
    // and the only way a player learned a quest had finished was if the
    // narrator happened to mention it. The narrator is not told either.
    let state = reducer(started(), { type: "SUBMIT", text: "go" });
    state = reducer(
      state,
      socket("turn_update", {
        narration: "The oven ticks as it cools.",
        quest_events: [
          { kind: "completed", quest_id: "bakery_apprentice", text: "Quest complete: Bakery Apprentice." },
          { kind: "started", quest_id: "lost_goat", text: "New: The Lost Goat." },
        ],
      }),
    );

    const quests = state.log.filter((e) => e.kind === "quest").map((e) => e.text);
    expect(quests).toEqual([
      "Quest complete: Bakery Apprentice.",
      "New: The Lost Goat.",
    ]);
  });

  it("adds nothing on a turn with no quest events", () => {
    let state = reducer(started(), { type: "SUBMIT", text: "go" });
    state = reducer(state, socket("turn_update", { narration: "Nothing happens." }));
    expect(state.log.some((e) => e.kind === "quest")).toBe(false);
  });

  it("ignores an event with no text rather than rendering a blank line", () => {
    let state = reducer(started(), { type: "SUBMIT", text: "go" });
    state = reducer(
      state,
      socket("turn_update", {
        narration: "Nothing happens.",
        quest_events: [{ kind: "advanced", quest_id: "x" }],
      }),
    );
    expect(state.log.some((e) => e.kind === "quest")).toBe(false);
  });
});

describe("a negotiated turn", () => {
  /**
   * `negotiation` has ridden the payload since the pipeline shipped and no
   * consumer ever read the key -- `grep -rn negotiation ui/src/` returned
   * nothing. Three of the five stories run plan -> negotiate -> commit, and a
   * player had no way to know a second agent had won, lost or given something
   * up.
   */
  const negotiated = (negotiation) =>
    reducer(
      started(),
      socket("turn_update", {
        narration: "She lets the sentence go unfinished.",
        choices: [],
        state: { location_id: "the_grid" },
        negotiation,
      })
    );

  it("keeps the negotiation for the turn it describes", () => {
    const state = negotiated({ ran: true, lead: "sophia", resolutions: [] });
    expect(state.negotiation.lead).toBe("sophia");
  });

  it("marks the entry when a side actually yielded", () => {
    const state = negotiated({
      ran: true,
      lead: "sophia",
      resolutions: [{ rule: "private_scene_finishes", winner: "sophia", loser: "gm" }],
    });
    expect(state.log.at(-1).negotiated).toBe(true);
  });

  it("does not mark a lead nobody contested", () => {
    // The confidence fallback records a winner and NO loser. Marking it would
    // tell the player a turn was fought over when it was only bookkeeping.
    const state = negotiated({
      ran: true,
      lead: "gm",
      resolutions: [{ rule: "confidence", winner: "gm", detail: "highest confidence leads" }],
    });
    expect(state.log.at(-1).negotiated).toBeFalsy();
  });

  it("does not mark a turn from a story that runs no pipeline", () => {
    // The flagship has one participant, so `ran` is false and no key ships.
    const state = negotiated(undefined);
    expect(state.negotiation).toBeNull();
    expect(state.log.at(-1).negotiated).toBeFalsy();
  });

  it("clears the previous turn's negotiation", () => {
    // It describes THIS turn. Sticky would leave the mark and the panel
    // reporting an argument two turns stale -- the `ending` field is sticky on
    // purpose and says so; this is the opposite case.
    const first = negotiated({
      ran: true,
      lead: "sophia",
      resolutions: [{ rule: "r", winner: "sophia", loser: "gm" }],
    });
    const second = reducer(
      first,
      socket("turn_update", { narration: "Quiet.", choices: [], state: {} })
    );
    expect(second.negotiation).toBeNull();
  });
});

describe("a rejoin (spec §6.6)", () => {
  const rejoining = (over = {}) => ({ ...started(), link: "rejoining", ...over });
  const join = (payload) => socket("game_started", { session_id: "s1", state: { location_id: "the_grid" }, ...payload });

  it("appends the last turn's narration once, and not again", () => {
    let state = rejoining();
    state = reducer(state, join({ turn_running: false, opening: { narration: "Neon hum.", choices: [{ id: "b", text: "Go" }], quest_events: [{ text: "A job, done." }] } }));
    expect(state.log.map((e) => e.text)).toEqual(["Rain on wet asphalt.", "Neon hum.", "A job, done."]);
    expect(state.choices).toEqual([{ id: "b", text: "Go" }]);
    state = reducer({ ...state, link: "rejoining" }, join({ turn_running: false, opening: { narration: "Neon hum.", quest_events: [{ text: "A job, done." }] } }));
    expect(state.log).toHaveLength(3);
  });

  it("keeps busy while the server says a turn is still running", () => {
    expect(reducer(rejoining(), join({ turn_running: true, opening: {} })).busy).toBe(true);
    expect(reducer(rejoining({ busy: true }), join({ turn_running: false, opening: {} })).busy).toBe(false);
  });

  it("reads an ending the turn locked while the socket was down, and keeps it", () => {
    const ending = { ending_id: "the_rope", title: "The Rope" };
    const state = reducer(rejoining(), join({ turn_running: false, opening: { ending } }));
    expect(state.ending).toEqual(ending);
    expect(reducer({ ...state, link: "rejoining" }, join({ turn_running: false, opening: {} })).ending).toEqual(ending);
  });

  it("offers Try again for a move the server dropped unanswered", () => {
    let state = reducer(rejoining(), { type: "SUBMIT", text: "Run" });
    state = reducer({ ...state, link: "rejoining" }, join({ turn_running: false, opening: { narration: "Rain on wet asphalt." } }));
    state = reducer(state, { type: "LINK", link: "live", banner: null, checkUnanswered: true });
    expect(state.banner).toMatchObject({ kind: "unanswered", action: "again" });
  });

  it("does not offer it when the move was answered", () => {
    let state = reducer(rejoining(), { type: "SUBMIT", text: "Run" });
    state = reducer({ ...state, link: "rejoining" }, join({ turn_running: false, opening: { narration: "You run." } }));
    state = reducer(state, { type: "LINK", link: "live", banner: null, checkUnanswered: true });
    expect(state.banner).toBeNull();
  });

  it("ignores the join's own miss while rejoining (the link resumes)", () => {
    const state = reducer(rejoining(), socket("error", { message: "session not found" }));
    expect(state.error).toBe("");
    // Anywhere else it is an error like any other.
    expect(reducer(started(), socket("error", { message: "session not found" })).error).toBe("session not found");
  });

  it("LINK sets connected from the state", () => {
    expect(reducer(initialState, { type: "LINK", link: "retrying", banner: null }).connected).toBe(false);
    expect(reducer(initialState, { type: "LINK", link: "refused", banner: null }).connected).toBe(false);
    expect(reducer(initialState, { type: "LINK", link: "live", banner: null }).connected).toBe(true);
  });

  it("BANNER_DISMISS clears the banner and RESET keeps the link", () => {
    const shown = reducer(initialState, { type: "LINK", link: "retrying", banner: { kind: "retrying" } });
    expect(reducer(shown, { type: "BANNER_DISMISS" }).banner).toBeNull();
    const reset = reducer(shown, { type: "RESET" });
    expect(reset.link).toBe("retrying");
    expect(reset.banner).toEqual({ kind: "retrying" });
  });
});

describe("resume_failed (Review 27)", () => {
  it("keeps its message for the start screen", () => {
    const state = reducer(started(), socket("resume_failed", { message: "That save is gone." }));
    expect(state.screen).toBe("start");
    expect(state.error).toBe("That save is gone.");
    expect(state.busy).toBe(false);
  });
});

describe("fix round 1 (T11 review)", () => {
  it("a resume does not re-append the narration the log already ends on (review 1)", () => {
    let state = started();
    state = reducer(state, socket("game_resumed", { session_id: "s2", opening: { narration: "Rain on wet asphalt." } }));
    expect(state.log.map((e) => e.text)).toEqual(["Rain on wet asphalt."]);
    state = reducer(state, socket("game_resumed", { session_id: "s3", opening: { narration: "The bell again." } }));
    expect(state.log.map((e) => e.text)).toEqual(["Rain on wet asphalt.", "The bell again."]);
  });

  it("a recovery's resume offers Try again for the move it lost (review 2)", () => {
    let state = { ...reducer(started(), { type: "SUBMIT", text: "Run" }), link: "resuming" };
    state = reducer(state, socket("game_resumed", { session_id: "s2", opening: { narration: "The bell counts the hour." } }));
    expect(state.sessionId).toBe("s2");
    expect(state.log.at(-1).text).toBe("The bell counts the hour."); // the echo is no longer last...
    state = reducer(state, { type: "LINK", link: "live", banner: null, checkUnanswered: true });
    expect(state.banner).toMatchObject({ kind: "unanswered", action: "again" }); // ...and it is still offered
    expect(state.pendingAgain).toBe(false);
  });

  it("a resume with nothing lost offers nothing", () => {
    let state = { ...started(), link: "resuming" };
    state = reducer(state, socket("game_resumed", { session_id: "s2", opening: { narration: "The bell." } }));
    state = reducer(state, { type: "LINK", link: "live", banner: null, checkUnanswered: true });
    expect(state.banner).toBeNull();
  });

  it("a late second answer to the join never clears a turn in flight (review 4)", () => {
    const join = (payload) => socket("game_started", { session_id: "s1", state: { location_id: "the_grid" }, ...payload });
    // The first answer goes live...
    let state = reducer({ ...started(), link: "rejoining" }, join({ turn_running: false, opening: { narration: "Neon hum.", choices: [{ id: "b", text: "Go" }] } }));
    state = reducer(state, { type: "LINK", link: "live", banner: null });
    // ...the player presses a move...
    state = reducer(state, { type: "SUBMIT", text: "Go" });
    const before = state.log.length;
    // ...and the join timer's second answer arrives.
    state = reducer(state, join({ turn_running: false, opening: { narration: "Neon hum.", choices: [{ id: "b", text: "Go" }] } }));
    expect(state.busy).toBe(true);
    expect(state.log).toHaveLength(before);
    expect(state.screen).toBe("scene");
  });
});

describe("fix round 2 (T11 re-review R1): a late join answer changes nothing", () => {
  const join = (payload) => socket("game_started", { session_id: "s1", state: { location_id: "the_grid" }, ...payload });

  it("(a) a late answer saying a turn runs, after the turn finished, never freezes an idle page", () => {
    // Live and idle: the move's turn_update has already arrived.
    let state = { ...reducer(started(), { type: "SUBMIT", text: "Run" }), link: "live" };
    state = reducer(state, socket("turn_update", { narration: "You run.", choices: [{ id: "b", text: "Stop" }] }));
    expect(state.busy).toBe(false);
    const late = reducer(state, join({ turn_running: true, opening: { narration: "Rain on wet asphalt." } }));
    expect(late.busy).toBe(false);
    expect(late).toBe(state); // nothing at all: the link re-joins if it must
  });

  it("(b) a late answer during a streaming move appends nothing under the stream", () => {
    let state = { ...reducer(started(), { type: "SUBMIT", text: "Run" }), link: "live" };
    state = reducer(state, socket("narration_delta", { text: "You run" }));
    const before = state.log.map((e) => e.text);
    const late = reducer(state, join({ turn_running: false, opening: { narration: "Neon hum.", quest_events: [{ text: "A job." }] } }));
    expect(late.log.map((e) => e.text)).toEqual(before);
    expect(late.streamingId).toBe(state.streamingId);
    expect(late.busy).toBe(true);
  });
});

describe("Try again after a recovery is matched by intent (final review 8)", () => {
  const chip = (over = {}) => ({ choiceId: "c3", custom: "", intent: { action: "travel", target: "wickmarket" }, ...over });
  const resumed = (choices) => {
    let state = { ...reducer(started(), { type: "SUBMIT", text: "Go to the market", move: chip() }), link: "resuming" };
    state = reducer(state, socket("game_resumed", { session_id: "s2", opening: { narration: "The bell.", choices } }));
    return reducer(state, { type: "LINK", link: "live", banner: null, checkUnanswered: true });
  };

  it("a restart's resume_* frame without the move offers no Try again, says so, and focuses the row", () => {
    const state = resumed([{ id: "resume_look", text: "Take stock" }, { id: "resume_wait", text: "Wait" }]);
    expect(state.banner).toMatchObject({ kind: "unanswered_lost", action: null });
    expect(state.banner.text).toMatch(/no longer on offer/);
    expect(state.againId).toBe("");
    expect(state.choiceFocus).toBe(1);
  });

  it("a resumed frame holding the same intent under a new id re-offers it with that id", () => {
    const state = resumed([
      { id: "resume_look", text: "Take stock" },
      { id: "resume_go_wickmarket", text: "Set out for Wickmarket", intent: { action: "travel", target: "wickmarket" } },
    ]);
    expect(state.banner).toMatchObject({ kind: "unanswered", action: "again" });
    expect(state.againId).toBe("resume_go_wickmarket");
  });

  it("retryTarget: typed text and a held chip resend as they were; an intent-less chip not held is lost", () => {
    expect(retryTarget({ choiceId: "custom", custom: "I wait", intent: null }, [])).toBe("");
    expect(retryTarget(chip(), [{ id: "c3", intent: { action: "travel", target: "wickmarket" } }])).toBe("");
    expect(retryTarget(chip({ intent: null }), [{ id: "c3" }])).toBe("");
    expect(retryTarget(chip({ intent: null }), [{ id: "resume_look" }])).toBeNull();
    expect(retryTarget(chip(), [{ id: "c3", intent: { action: "travel", target: "elsewhere" } }])).toBeNull();
  });

  it("a fresh press clears the matched id; a retry keeps the move it retries", () => {
    let state = resumed([{ id: "x", intent: { action: "travel", target: "wickmarket" } }]);
    expect(state.againId).toBe("x");
    const retried = reducer(state, { type: "SUBMIT", text: "" });
    expect(retried.againId).toBe("x");
    expect(retried.move.choiceId).toBe("c3");
    const fresh = reducer(state, { type: "SUBMIT", text: "Wait", move: { choiceId: "y", custom: "", intent: null } });
    expect(fresh.againId).toBe("");
  });

  it("the server's stale-choice refusal offers nothing to retry and focuses the row", () => {
    let state = reducer(started(), { type: "SUBMIT", text: "Go", move: chip() });
    state = reducer(state, socket("turn_error", { message: "That choice is no longer on offer. Choose again.", busy: false, stale_choice: true }));
    expect(state.busy).toBe(false);
    expect(state.errorFinal).toBe(true);
    expect(state.choiceFocus).toBe(1);
    expect(reducer(state, { type: "SUBMIT", text: "Wait" }).errorFinal).toBe(false);
  });
});

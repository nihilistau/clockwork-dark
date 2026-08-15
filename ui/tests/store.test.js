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

import { createStore, initialState, reducer } from "../src/core/store.js";

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

  it("keeps a fade card for its own turn and no longer", () => {
    // A fade belongs to the scene that faded. Carrying it forward would leave
    // last scene's card sitting under this scene's narration.
    let state = reducer(started(), { type: "SUBMIT", text: "go" });
    state = reducer(state, socket("turn_update", { fade_card: { heading: "It went quiet." } }));
    expect(state.fadeCard.heading).toBe("It went quiet.");

    state = reducer(state, socket("turn_update", { narration: "The next thing." }));
    expect(state.fadeCard).toBeNull();
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

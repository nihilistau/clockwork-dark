/**
 * Start screen — name, archetype, seed.
 *
 * There was no start screen at all: the client hardcoded
 * `{player_name: "Traveler", archetype: "wayfarer"}`, so every run was the same
 * person and `archetype` reached nothing but a prompt line.
 */
import React, { useEffect, useState } from "react";
import { fetchArchetypes, fetchGames } from "../api.js";

// Shown only until GET /api/archetypes answers, and only if it never does.
//
// This used to be the whole list, hardcoded -- the third and last copy of the
// flagship's answer, and the only one carrying display text. Two problems with
// that: a second story offered its own archetypes in the game picker and then
// drew Edgewood's three here, and the copy had DRIFTED from the rules file it
// claimed to match (it advertised "lore · sympathy" for the tinker where
// data/rules/archetypes.yaml grants craft and lore, so the screen promised a
// skill bonus the engine does not give).
//
// Ids still must resolve against the active story's rules: an id that does not
// falls back to the default, so the player's choice would be quietly discarded.
const ARCHETYPE_FALLBACK = [
  {
    id: "wayfarer",
    name: "Wayfarer",
    blurb: "Cloak, staff, road boots. You have slept under more hedges than roofs.",
    note: "",
  },
];

/**
 * The game picker.
 *
 * GET /api/games has been live with a catalogue, `playable`, `problems` and
 * `active` flags, and two games on disk, and nothing rendered it — a player
 * could not learn that a second story existed.
 *
 * Selecting one does NOT switch it. engine/games/api.py is explicit that
 * activation is a launch-time decision, because swapping stories under a live
 * session would invalidate every save and cache mid-turn. So the picker shows
 * what is installed, marks what is running, and hands over the exact command
 * for anything else. An honest picker beats a button that lies.
 */
function GamePicker() {
  const [catalogue, setCatalogue] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let live = true;
    fetchGames()
      .then((data) => live && setCatalogue(data))
      .catch(() => {
        /* one game is the normal case; a missing catalogue hides the picker */
      });
    return () => {
      live = false;
    };
  }, []);

  const games = catalogue?.games || [];
  if (games.length === 0) return null;
  const active = games.find((g) => g.active) || games[0];

  return (
    <div className="picker">
      <button
        type="button"
        className="picker__current"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        disabled={games.length < 2}
      >
        <span className="picker__kicker">Story</span>
        <span className="picker__title">{active.title}</span>
        {games.length > 1 && (
          <span className="picker__count">{games.length} installed</span>
        )}
      </button>

      {open && (
        <ul className="picker__list">
          {games.map((game) => (
            <li
              key={game.slug}
              className={`pickerrow ${game.active ? "is-active" : ""} ${
                game.playable ? "" : "is-broken"
              }`}
            >
              <div className="pickerrow__head">
                <span className="pickerrow__title">{game.title}</span>
                <span className="pickerrow__version">v{game.version}</span>
                {game.active && <span className="pill pill--brass">running</span>}
              </div>
              <p className="pickerrow__blurb">{game.blurb}</p>
              {!game.playable && (
                <p className="pickerrow__problem">
                  Will not load: {game.problems.join("; ")}
                </p>
              )}
              {!game.active && game.playable && (
                <p className="pickerrow__how">
                  Launch with <code>python launcher.py --game {game.slug}</code>
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * The start screen.
 *
 * Two things here belong to a story and nothing else does: the wordmark and the
 * opening paragraph. Both used to be literals in this file, so a second story
 * booted into "The Clockwork Dark" and an invitation to walk to Edgewood. They
 * are plugin slots now (`Wordmark`, `StartIntro`); with no plugin the screen
 * falls back to the catalogue's own title, which the server already knows.
 */
export default function Start({ onBegin, busy, onOpenSaves, story = {} }) {
  const Wordmark = story.Wordmark || null;
  const Intro = story.StartIntro || null;
  const [name, setName] = useState("");
  const [archetypes, setArchetypes] = useState(ARCHETYPE_FALLBACK);
  const [archetype, setArchetype] = useState("");
  const [seed, setSeed] = useState("");

  // The active story's offerings, ids from its manifest and display text from
  // its rules file. Selecting the first only once they arrive, so the choice
  // the player sees selected is always one the engine will actually honour.
  useEffect(() => {
    let live = true;
    fetchArchetypes()
      .then((rows) => {
        if (!live) return;
        // An EMPTY list is an answer, not a failure. A story whose player is
        // simply a person who walked in declares `archetypes: []`, and the
        // route returns nothing -- so bailing on `!rows.length` left the
        // hardcoded fallback on screen and offered The Wicked Garden a
        // Clockwork wayfarer. Only a rejected fetch keeps the fallback.
        setArchetypes(rows);
        setArchetype((current) => current || rows[0]?.id || "");
      })
      .catch(() => {
        /* the fallback is already on screen; a dead route must not block a run */
      });
    return () => {
      live = false;
    };
  }, []);

  function submit(event) {
    event.preventDefault();
    onBegin({
      player_name: name.trim() || "Traveler",
      // Empty lets the server ask the active story's manifest rather than the
      // client asserting a default it may have no business choosing.
      archetype: archetype || archetypes[0]?.id || "",
      seed: seed.trim() ? Number(seed.trim()) : null,
    });
  }

  return (
    <div className="start">
      <form className="start__card" onSubmit={submit}>
        {Wordmark ? (
          <Wordmark />
        ) : (
          <h1 className="start__wordmark">{story.title || "A story"}</h1>
        )}

        <GamePicker />
        {Intro && <Intro />}

        <label className="field">
          <span className="field__label">Your name</span>
          <input
            className="field__input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Traveler"
            maxLength={32}
            autoFocus
          />
        </label>

        {/* Hidden entirely for a story with no classes -- an empty fieldset
            with a legend asking "what you were, before this" and nothing to
            pick is worse than no question. */}
        <fieldset className="archetypes" hidden={archetypes.length === 0}>
          <legend className="field__label">What you were, before this</legend>
          {archetypes.map((option) => (
            <label
              key={option.id}
              className={`archetype ${archetype === option.id ? "is-selected" : ""}`}
            >
              <input
                type="radio"
                name="archetype"
                value={option.id}
                checked={archetype === option.id}
                onChange={() => setArchetype(option.id)}
                // Without this the control is announced by its value
                // ("hedge_wise") rather than by the name a player would read.
                aria-label={`${option.name} — ${option.blurb}`}
              />
              <span className="archetype__head">
                <span className="archetype__name">{option.name}</span>
                <span className="archetype__note">{option.note}</span>
              </span>
              <span className="archetype__blurb">{option.blurb}</span>
            </label>
          ))}
        </fieldset>

        <label className="field field--inline">
          <span className="field__label">Seed</span>
          <input
            className="field__input field__input--short"
            value={seed}
            onChange={(e) => setSeed(e.target.value.replace(/[^0-9]/g, ""))}
            placeholder="random"
            inputMode="numeric"
          />
          <span className="field__hint">Same seed, same village.</span>
        </label>

        <button type="submit" className="btn btn--lg" disabled={busy}>
          {busy ? "Waking…" : story.beginLabel || "Begin"}
        </button>

        {/* The save browser was reachable only from inside a run, so a player
            who closed the tab on day 30 had no way back to it from here. */}
        {onOpenSaves && (
          <button type="button" className="btn btn--ghost start__continue" onClick={onOpenSaves}>
            Continue a saved run
          </button>
        )}
      </form>
    </div>
  );
}

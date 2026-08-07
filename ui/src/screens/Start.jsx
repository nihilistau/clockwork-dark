/**
 * Start screen — name, archetype, seed.
 *
 * There was no start screen at all: the client hardcoded
 * `{player_name: "Traveler", archetype: "wayfarer"}`, so every run was the same
 * person and `archetype` reached nothing but a prompt line.
 */
import React, { useState } from "react";

// Ids MUST match data/rules/archetypes.yaml -- an id that does not resolve
// silently falls back to the default, so the player's choice would be quietly
// discarded rather than failing loudly.
const ARCHETYPES = [
  {
    id: "wayfarer",
    name: "Wayfarer",
    blurb: "Cloak, staff, road boots. You have slept under more hedges than roofs.",
    note: "survival · stealth",
  },
  {
    id: "hearthkeeper",
    name: "Hearthkeeper",
    blurb: "Apron, rolled sleeves, flour to the elbow. You feed people. That is not nothing.",
    note: "craft · persuasion",
  },
  {
    id: "tinker_apprentice",
    name: "Tinker's apprentice",
    blurb: "Half-learned trade, borrowed tools, and a habit of taking things apart.",
    note: "lore · sympathy",
  },
];

export default function Start({ onBegin, busy }) {
  const [name, setName] = useState("");
  const [archetype, setArchetype] = useState("wayfarer");
  const [seed, setSeed] = useState("");

  function submit(event) {
    event.preventDefault();
    onBegin({
      player_name: name.trim() || "Traveler",
      archetype,
      seed: seed.trim() ? Number(seed.trim()) : null,
    });
  }

  return (
    <div className="start">
      <form className="start__card" onSubmit={submit}>
        <h1 className="start__wordmark">
          The Clockwork <span>Dark</span>
        </h1>
        <p className="start__intro">
          You wake at the forest's edge with the taste of iron and no clear reason for
          it. Ahead, hearth smoke. Somewhere further in, something is winding itself
          into the bones of the world — and it will keep winding whether you become a
          hero or a baker.
        </p>

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

        <fieldset className="archetypes">
          <legend className="field__label">What you were, before this</legend>
          {ARCHETYPES.map((option) => (
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
          {busy ? "Waking…" : "Step into the clearing"}
        </button>
      </form>
    </div>
  );
}

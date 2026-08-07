/**
 * Header and footer chrome.
 *
 * WorldClock reads "Day 12 · Dusk" rather than the raw 24h "Day 12 · 19:00" the
 * old client printed: the game has a daypart concept and the fiction speaks in
 * it. The gear glyph is discovery-gated, per the design system.
 */
import React from "react";

const DAYPART = {
  dawn: "Dawn",
  day: "Day",
  dusk: "Dusk",
  night: "Night",
};

export function GearMark({ discovered }) {
  return (
    <svg
      className={`gear ${discovered ? "gear--turning" : ""}`}
      viewBox="0 0 24 24"
      width="16"
      height="16"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zm0 1.6a1.9 1.9 0 1 1 0 3.8 1.9 1.9 0 0 1 0-3.8z"
        fill="currentColor"
      />
      <path
        d="M12 2.4l1.5 2.2 2.6-.5.4 2.6 2.4 1.1-1.2 2.4 1.2 2.4-2.4 1.1-.4 2.6-2.6-.5L12 21.6l-1.5-2.2-2.6.5-.4-2.6-2.4-1.1 1.2-2.4-1.2-2.4 2.4-1.1.4-2.6 2.6.5L12 2.4z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.1"
        opacity="0.75"
      />
    </svg>
  );
}

export function Header({ world, phase }) {
  const day = world?.world_day ?? 1;
  const part = DAYPART[world?.time_of_day] || "Day";
  // The gear only turns once the world has started to go wrong -- it is a
  // diegetic tell, not a decoration.
  const discovered = phase && phase !== "dormant";

  return (
    <header className="chrome chrome--top">
      <div className="chrome__left">
        <GearMark discovered={discovered} />
        <h1 className="chrome__title">
          {world?.location_id ? prettyPlace(world.location_id) : "The Clockwork Dark"}
        </h1>
      </div>
      <div className="chrome__right" aria-label="World clock">
        <span className="ring" aria-hidden="true" />
        <span className="clock">
          Day {day} · {part}
        </span>
      </div>
    </header>
  );
}

export function Footer({ world, connected, error, onOpenSaves, onOpenSettings,
                         onOpenJournal, onOpenCodex, onOpenTrade, muted, onToggleMute }) {
  const day = world?.world_day ?? 1;
  const part = DAYPART[world?.time_of_day] || "Day";

  return (
    <footer className="chrome chrome--bottom">
      <span className="clock">
        Day {day} · {part}
      </span>
      <div className="chrome__right">
        {error ? (
          <span className="status status--error" role="status">
            {error}
          </span>
        ) : (
          <span className={`status ${connected ? "" : "status--warn"}`} role="status">
            {connected ? "Connected" : "Reconnecting…"}
          </span>
        )}
        {/* The glyphs are decorative; every one of these carries a real label
            because a row of unlabelled symbols is unusable by voice or screen
            reader, and the emoji names ("speaker with cancellation stroke")
            say nothing about what the control does here. */}
        <button type="button" className="icon-btn" onClick={onOpenJournal} aria-label="Journal">
          <span aria-hidden="true">❧</span>
        </button>
        <button type="button" className="icon-btn" onClick={onOpenCodex} aria-label="Codex">
          <span aria-hidden="true">✦</span>
        </button>
        <button type="button" className="icon-btn" onClick={onOpenTrade} aria-label="Barter">
          <span aria-hidden="true">⚖</span>
        </button>
        <button type="button" className="icon-btn" onClick={onToggleMute}
                aria-pressed={muted} aria-label={muted ? "Unmute narration" : "Mute narration"}>
          <span aria-hidden="true">{muted ? "🔇" : "🔊"}</span>
        </button>
        <button type="button" className="icon-btn" onClick={onOpenSaves} aria-label="Saved runs">
          <span aria-hidden="true">⌸</span>
        </button>
        <button type="button" className="icon-btn" onClick={onOpenSettings} aria-label="Settings">
          <span aria-hidden="true">⚙</span>
        </button>
      </div>
    </footer>
  );
}

export function prettyPlace(id) {
  return String(id).replace(/_/g, " ");
}

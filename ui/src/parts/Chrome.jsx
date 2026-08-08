/**
 * Header and footer chrome.
 *
 * WorldClock reads "Day 12 · Dusk" rather than the raw 24h "Day 12 · 19:00" the
 * old client printed: the game has a daypart concept and the fiction speaks in
 * it. The gear glyph is discovery-gated, per the design system.
 *
 * ICONOGRAPHY
 * -----------
 * The footer used to render six unlabelled text glyphs: ❧ ✦ ⚖ 🔊 ⌸ ⚙. That row
 * had three separate problems. `⌸` (U+2338 APL QUAD EQUAL) is not in any font
 * Windows ships by default, so the "saved runs" control rendered as a tofu box.
 * `🔊` is a full-colour emoji sitting among five monochrome symbols, so one
 * button was blue and the rest were brass. And none of them were drawn for this
 * game -- they were the nearest available characters.
 *
 * These are drawn: one 24px grid, `currentColor` throughout so they take the
 * phase tint, 1.4 stroke, round joins, no fills except where a mark has to read
 * solid at 20px. Every button keeps its aria-label -- an icon is a picture of a
 * word, not a replacement for one.
 */
import React from "react";

const DAYPART = {
  dawn: "Dawn",
  day: "Day",
  dusk: "Dusk",
  night: "Night",
};

function Icon({ children, size = 20 }) {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

/* A bound journal, seen closed: boards, spine, and the ribbon marking the
   page you stopped on. */
function JournalIcon() {
  return (
    <Icon>
      <path d="M7 3.6h10.4a1.6 1.6 0 0 1 1.6 1.6v13.6a1.6 1.6 0 0 1-1.6 1.6H7" />
      <path d="M7 3.6A1.9 1.9 0 0 0 5.1 5.5v13a1.9 1.9 0 0 0 1.9 1.9" />
      <path d="M5.1 17.4h1.9" />
      <path d="M13.9 3.6v6.3l-1.7-1.4-1.7 1.4V3.6" />
    </Icon>
  );
}

/* A folded travelling map with one place ringed on it. The Atlas is the first
   tab of the codex and it is the only one a player recognises by shape. */
function AtlasIcon() {
  return (
    <Icon>
      <path d="M3.6 6.6 9 4.3l6 2.3 5.4-2.3v13.1L15 19.7l-6-2.3-5.4 2.3z" />
      <path d="M9 4.3v13.1M15 6.6v13.1" />
      <circle cx="12" cy="11.2" r="1.5" fill="currentColor" stroke="none" />
    </Icon>
  );
}

/* A balance beam. Barter in this world is weighing what you have against what
   they will part with -- the trade screen draws the same beam full size. */
function ScalesIcon() {
  return (
    <Icon>
      <path d="M12 4.4v15.2M8.4 19.6h7.2" />
      <path d="M4.2 7.4h15.6" />
      <path d="M4.2 7.4 2 12.4h4.4zM19.8 7.4l-2.2 5H22z" />
      <circle cx="12" cy="4.4" r="1.1" fill="currentColor" stroke="none" />
    </Icon>
  );
}

/* A hand bell. The narration is read aloud by a voice, not played from a
   speaker cone, and the muted state is the same bell with the rope cut. */
function BellIcon({ muted }) {
  return (
    <Icon>
      <path d="M6.9 16.4c1.4-1.3 1.8-3 1.8-5.1 0-2.4 1.5-4.2 3.3-4.2s3.3 1.8 3.3 4.2c0 2.1.4 3.8 1.8 5.1z" />
      <path d="M6.5 16.4h11" />
      <path d="M10.4 18.2a1.7 1.7 0 0 0 3.2 0" />
      <path d="M12 4.6v2.5" />
      {muted && <path d="M4.6 19.8 19.4 4.2" strokeWidth="1.6" />}
    </Icon>
  );
}

/* A stack of ledger leaves with the top one dog-eared: the saved runs are
   pages of the same book, filed. */
function LedgerIcon() {
  return (
    <Icon>
      <path d="M9.2 3.6h5.3l4 4V17a1.6 1.6 0 0 1-1.6 1.6H9.2A1.6 1.6 0 0 1 7.6 17V5.2a1.6 1.6 0 0 1 1.6-1.6z" />
      <path d="M14.5 3.6v4h4" />
      <path d="M10.4 11.2h4.6M10.4 14.2h4.6" />
      <path d="M4.8 7.6v11.2a1.6 1.6 0 0 0 1.6 1.6h8.3" />
    </Icon>
  );
}

/* A rucksack. The pack screen is the only place in the product that shows you
   what you are physically carrying, so the mark is the thing itself. */
function PackIcon() {
  return (
    <Icon>
      <path d="M7.4 9.2h9.2a2.3 2.3 0 0 1 2.3 2.3v7.1a1.6 1.6 0 0 1-1.6 1.6H6.7a1.6 1.6 0 0 1-1.6-1.6v-7.1a2.3 2.3 0 0 1 2.3-2.3z" />
      <path d="M9.3 9.2V7.1a2.7 2.7 0 0 1 5.4 0v2.1" />
      <path d="M5.1 13.7h13.8" />
      <path d="M10.7 15.8h2.6v2.6h-2.6z" />
    </Icon>
  );
}

/* The world, held still. A pause mark inside the frame — the menu is the one
   control that stops the clock, and the clock is what this game is about. */
function PauseIcon() {
  return (
    <Icon>
      <rect x="4.3" y="4.3" width="15.4" height="15.4" rx="2.2" />
      <path d="M10 8.8v6.4M14 8.8v6.4" />
    </Icon>
  );
}

/* Ledger rules with the settings slid along them. Deliberately not a gear:
   the gear is the masthead motif and means "the world is turning", so
   spending it on a preferences button would spend the brand on plumbing. */
function SlidersIcon() {
  return (
    <Icon>
      <path d="M4 7.4h16M4 12h16M4 16.6h16" />
      <circle cx="9" cy="7.4" r="2" fill="var(--surface-chrome)" />
      <circle cx="15.4" cy="12" r="2" fill="var(--surface-chrome)" />
      <circle cx="7.6" cy="16.6" r="2" fill="var(--surface-chrome)" />
    </Icon>
  );
}

/**
 * The masthead gear.
 *
 * This is the geometry of Design_files/assets/gear-motif.svg, inlined rather
 * than <img>-linked so it inherits `currentColor` and therefore corrupts with
 * the phase; the shipped file bakes in #8b4513 and would sit at DORMANT brass
 * while the rest of the frame went chartreuse. The file itself is still used,
 * as the mask for the corruption filigree in index.css.
 *
 * It was a 16px hand-drawn approximation at opacity 0.55 -- small enough and
 * faint enough that the one piece of brand furniture on the play screen read
 * as a smudge.
 */
export function GearMark({ discovered }) {
  return (
    <svg
      className={`gear ${discovered ? "gear--turning" : ""}`}
      viewBox="0 0 48 48"
      width="22"
      height="22"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="24" cy="24" r="6.5" />
      <circle cx="24" cy="24" r="1.6" fill="currentColor" stroke="none" />
      <g>
        <path d="M24 5.5v5" />
        <path d="M24 37.5v5" />
        <path d="M5.5 24h5" />
        <path d="M37.5 24h5" />
        <path d="M11 11l3.5 3.5" />
        <path d="M33.5 33.5L37 37" />
        <path d="M37 11l-3.5 3.5" />
        <path d="M14.5 33.5L11 37" />
      </g>
      {/* the hands — this is a clock as much as a gear */}
      <path d="M24 24l3 -2.2" strokeWidth="1.2" />
      <path d="M24 24l-1.6 2.6" strokeWidth="1.2" />
    </svg>
  );
}

export function Header({ world, phase, phaseCopy, onOpenMenu }) {
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
        {/* The evil phase lives here rather than in its own `.chromebar` row.
            That row cost a full band of vertical space on a screen where the
            scene column had 567px of 768 to work with -- and the art is the
            thing the player asked to be bigger. Same information, no band.
            Rendered only when the caller supplies the copy, so the header
            keeps working for any screen that does not have a phase to show. */}
        {phaseCopy && (
          <button
            type="button"
            className={`phasepill phasepill--${phase || "dormant"}`}
            onClick={onOpenMenu}
            title={phaseCopy.line}
          >
            <span className="phasepill__kicker">The pattern is</span>
            <span className="phasepill__word">{phaseCopy.word}</span>
          </button>
        )}
        <span className="ring" aria-hidden="true" />
        <span className="clock">
          Day {day} · {part}
        </span>
      </div>
    </header>
  );
}

/**
 * The footer.
 *
 * `onOpenPack` and `onOpenMenu` are optional: the pack and the pause menu are
 * keyboard-only (I and Esc) until Scene.jsx forwards them, and a control that
 * exists only as a key press is a control most players never find. The buttons
 * render the moment the handlers arrive; until then the row is the six it was.
 */
export function Footer({ world, connected, error, onOpenSaves, onOpenSettings,
                         onOpenJournal, onOpenCodex, onOpenTrade, onOpenPack,
                         onOpenMenu, muted, onToggleMute }) {
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
        {/* The icons are decorative; every button keeps its real label because
            a row of unlabelled marks is unusable by voice or screen reader. */}
        {onOpenPack && (
          <button type="button" className="icon-btn" onClick={onOpenPack}
                  aria-label="The pack" title="The pack (I)">
            <PackIcon />
          </button>
        )}
        <button type="button" className="icon-btn" onClick={onOpenJournal} aria-label="Journal">
          <JournalIcon />
        </button>
        <button type="button" className="icon-btn" onClick={onOpenCodex} aria-label="Codex">
          <AtlasIcon />
        </button>
        <button type="button" className="icon-btn" onClick={onOpenTrade} aria-label="Barter">
          <ScalesIcon />
        </button>
        <button type="button" className="icon-btn" onClick={onToggleMute}
                aria-pressed={muted} aria-label={muted ? "Unmute narration" : "Mute narration"}>
          <BellIcon muted={muted} />
        </button>
        <button type="button" className="icon-btn" onClick={onOpenSaves} aria-label="Saved runs">
          <LedgerIcon />
        </button>
        <button type="button" className="icon-btn" onClick={onOpenSettings} aria-label="Settings">
          <SlidersIcon />
        </button>
        {onOpenMenu && (
          <button type="button" className="icon-btn" onClick={onOpenMenu}
                  aria-label="Menu" title="Menu (Esc)">
            <PauseIcon />
          </button>
        )}
      </div>
    </footer>
  );
}

export function prettyPlace(id) {
  return String(id).replace(/_/g, " ");
}

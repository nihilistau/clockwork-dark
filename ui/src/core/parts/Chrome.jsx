/**
 * Header and footer chrome.
 *
 * WorldClock reads "Day 12 · Dusk" rather than the raw 24h "Day 12 · 19:00" the
 * old client printed: the game has a daypart concept and the fiction speaks in
 * it.
 *
 * WHAT MOVED OUT
 * --------------
 * The masthead gear and the phase pill were drawn here. Both are The Clockwork
 * Dark's furniture -- a clockwork motif and a four-phase corruption tell -- so
 * the header now takes them as `mark` and `badge` nodes and the flagship passes
 * its own. Same for the journal / codex / barter buttons: those are three of
 * the flagship's overlays, and the footer builds its row from whatever overlays
 * the active story declares. Four controls stay wired in because they belong to
 * the client rather than to any story: mute, saved runs, settings, pause.
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
 * story's tint, 1.4 stroke, round joins, no fills except where a mark has to
 * read solid at 20px. Every button keeps its aria-label -- an icon is a picture
 * of a word, not a replacement for one.
 */
import React from "react";

const DAYPART = {
  dawn: "Dawn",
  day: "Day",
  dusk: "Dusk",
  night: "Night",
};

/** The 24px icon shell. Exported so a story draws its overlay marks to match. */
export function Icon({ children, size = 20 }) {
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

/* The world, held still. A pause mark inside the frame — the menu is the one
   control that stops the clock. */
function PauseIcon() {
  return (
    <Icon>
      <rect x="4.3" y="4.3" width="15.4" height="15.4" rx="2.2" />
      <path d="M10 8.8v6.4M14 8.8v6.4" />
    </Icon>
  );
}

/* Ledger rules with the settings slid along them. Deliberately not a gear: a
   gear is a masthead motif in at least one story and means "the world is
   turning", so spending it on a preferences button would spend the brand on
   plumbing. */
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

export function Header({ world, title, mark, badge }) {
  const day = world?.world_day ?? 1;
  const part = DAYPART[world?.time_of_day] || "Day";

  return (
    <header className="chrome chrome--top">
      <div className="chrome__left">
        {mark}
        <h1 className="chrome__title">
          {world?.location_id ? prettyPlace(world.location_id) : title || "A story"}
        </h1>
      </div>
      <div className="chrome__right" aria-label="World clock">
        {/* A story's badge lives here rather than in its own `.chromebar` row.
            That row cost a full band of vertical space on a screen where the
            scene column had 567px of 768 to work with -- and the art is the
            thing the player asked to be bigger. Same information, no band. */}
        {badge}
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
 * `overlays` is whatever the active story declared. With no plugin the row is
 * the four client controls, which is a complete and honest footer -- there is
 * simply nothing story-specific to open.
 */
export function Footer({ world, connected, error, overlays = [], onOpenOverlay,
                         onOpenSaves, onOpenSettings, onOpenMenu,
                         muted, onToggleMute }) {
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
        {overlays.map((overlay) => (
          <button
            key={overlay.id}
            type="button"
            className="icon-btn"
            onClick={() => onOpenOverlay(overlay.id)}
            aria-label={overlay.label}
            title={overlay.key ? `${overlay.label} (${overlay.key.toUpperCase()})` : overlay.label}
          >
            {overlay.Icon ? <overlay.Icon /> : overlay.label.slice(0, 1)}
          </button>
        ))}
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

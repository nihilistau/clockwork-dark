/**
 * One app on the home screen: a tile, its name, and its unread badge (the
 * payload's `apps[].badge`, spec §17.3). The tile's colour is the app's own
 * token (theme/tokens.css), never a colour spelled here.
 */
import React from "react";

const GLYPHS = {
  texts: "T",
  natter: "N",
  matchstick: "M",
  front_porch: "F",
  games: "G",
  photos: "P",
  calendar: "C",
  contacts: "@",
  settings: "S",
  places: "↗",
};

export default function AppIcon({ app, onOpen, dock = false }) {
  const badge = Number(app.badge) || 0;
  return (
    <button
      type="button"
      className={`rr-icon${dock ? " rr-icon--dock" : ""}`}
      data-app={app.id}
      data-testid={`app-${app.id}`}
      aria-label={badge ? `${app.label}, ${badge} unread` : app.label}
      onClick={() => onOpen(app.id)}
    >
      <span className="rr-icon__tile" aria-hidden="true">
        {GLYPHS[app.id] || String(app.label || "?")[0]}
      </span>
      {badge > 0 && (
        <span className="rr-icon__badge" data-testid={`badge-${app.id}`} aria-hidden="true">
          {badge > 99 ? "99+" : badge}
        </span>
      )}
      <span className="rr-icon__label">{app.label}</span>
    </button>
  );
}

/**
 * The phone's top line: the in-game time, the side button (lock the phone,
 * where "Put it down" lets time pass), and the way to the pause menu.
 */
import React from "react";

import { clockOf } from "./format.js";

export default function StatusBar({ now, onOpenMenu, onLock = null, wall = false }) {
  return (
    <div className={`rr-status${wall ? " rr-status--wall" : ""}`}>
      <span className="rr-status__time" data-testid="status-time">{clockOf(now)}</span>
      <span className="rr-status__day">{now ? `${now.weekday} · Day ${now.day}` : ""}</span>
      {onLock && (
        <button type="button" className="rr-status__lock" aria-label="Lock" onClick={onLock}>
          <span aria-hidden="true">⏻</span>
        </button>
      )}
      {onOpenMenu && (
        <button type="button" className="rr-status__menu" aria-label="Menu" onClick={onOpenMenu}>
          <span aria-hidden="true">≡</span>
        </button>
      )}
    </div>
  );
}

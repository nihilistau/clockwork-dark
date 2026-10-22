/**
 * The phone's top line: the in-game time, "Put the phone down" (v0.23.0: the world comes forward, the
 * `put_down` action; shown while the phone is up), the side button (lock the phone) and the way to the
 * pause menu.
 */
import React from "react";

import { clockOf } from "./format.js";

export default function StatusBar({ now, onOpenMenu, onLock = null, onPutDown = null, wall = false }) {
  return (
    <div className={`rr-status${wall ? " rr-status--wall" : ""}`}>
      <span className="rr-status__time" data-testid="status-time">{clockOf(now)}</span>
      <span className="rr-status__day">{now ? (
          <>
            {now.weekday}
            <span className="rr-status__n"> · Day {now.day}</span>
          </>
        ) : (
          ""
        )}</span>
      {onPutDown && (
        <button type="button" className="rr-status__down" onClick={onPutDown}>
          Put the phone down
        </button>
      )}
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

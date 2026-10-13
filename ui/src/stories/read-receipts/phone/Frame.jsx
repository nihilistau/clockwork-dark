/**
 * The phone itself (spec §18.3). At 900px wide and over: a bezel, centred,
 * `min(100vh - header, 860px)` tall at 9:19.5. Under 900px: no bezel, the
 * screen fills the viewport. The sizes are the stylesheet's (theme/read-receipts.css);
 * this only lays out the parts. `side` is the open contact card at 1200px
 * wide and over (spec §18.3): a sheet beside the phone, not inside it.
 */
import React from "react";

export default function Frame({ title, onOpenMenu, onOpenSaves, side = null, children }) {
  return (
    <div className="rr" data-testid="phone-frame">
      <header className="rr-top">
        <span className="rr-top__title">{title}</span>
        <span className="rr-top__actions">
          {onOpenSaves && (
            <button type="button" className="rr-top__btn" onClick={onOpenSaves}>
              Saves
            </button>
          )}
          {onOpenMenu && (
            <button type="button" className="rr-top__btn" onClick={onOpenMenu}>
              Menu
            </button>
          )}
        </span>
      </header>
      <div className="rr-stage">
        <div className="rr-frame">
          <div className="rr-screen">{children}</div>
        </div>
        {side && (
          <aside className="rr-side" aria-label="Contact card">
            {side}
          </aside>
        )}
      </div>
    </div>
  );
}

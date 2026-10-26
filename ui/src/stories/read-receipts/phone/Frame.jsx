/**
 * The phone itself (spec §18.3). At 900px wide and over: a bezel, centred,
 * `min(100vh - header, 860px)` tall at 9:19.5. Under 900px: no bezel, the
 * screen fills the viewport. The sizes are the stylesheet's (theme/read-receipts.css);
 * this only lays out the parts. `side` is the open contact card at 1200px
 * wide and over (spec §18.3): a sheet beside the phone, not inside it.
 *
 * Two layers (v0.23.0 spec §14.1): with a `world` node the stage holds the world and the phone. At 1200px wide
 * and over the phone layer sits BESIDE the world (`beside`); under it, the phone layer COVERS the world
 * (`over`) while the phone is up, the world dimmed behind, and goes away while it is down. With no `world`
 * (a phone block older than v0.23.0) the stage is the phone alone, as v0.22.0 drew it.
 */
import React from "react";

export default function Frame({ title, onOpenMenu, onOpenSaves, side = null, world = null, phoneUp = true, wide = false, children }) {
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
      <div className="rr-stage" data-layers={world ? "two" : "one"}>
        {world && (
          // The layer behind a raised phone is dimmed and not there to reach (T14 b2): inert, so neither Tab
          // nor a screen reader gets into it.
          <div
            className={`rr-world-layer${!wide && phoneUp ? " dimmed" : ""}`}
            data-testid="rr-world-layer"
            {...(!wide && phoneUp ? { inert: "", "aria-hidden": "true" } : {})}
          >
            {world}
          </div>
        )}
        <div
          className={`rr-phone-layer ${wide ? "beside" : "over"} ${phoneUp ? "up" : "down"}`}
          data-testid="rr-phone-layer"
          {...(!wide && !phoneUp && world ? { inert: "", "aria-hidden": "true" } : {})}
        >
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
    </div>
  );
}

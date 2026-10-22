/**
 * The Places app (v0.23.0 spec §8.5, §14.2): every place the player can go from where they are, from the
 * payload's `places.venues` (`world.places_targets`, the same list the phone verb `go` accepts, so every
 * row is accepted). Choosing one puts the phone down and goes; the engine charges the travel and says so.
 * Names only: no distances, no ranks.
 */
import React from "react";

export default function Places({ venues = [], act, pending = null }) {
  const busy = Boolean(pending && pending.action === "go");
  return (
    <section className="rr-app rr-app--places" aria-label="Places">
      <h2 className="rr-app__title" tabIndex={-1}>Places</h2>
      <div className="rr-app__body">
        {venues.length === 0 ? (
          <p className="rr-card__sub rr-games__none">Nowhere to go from here right now.</p>
        ) : (
          <ul className="rr-places">
            {venues.map((v) => (
              <li key={v.id} data-venue={v.id}>
                <button
                  type="button"
                  className="rr-btn rr-btn--quiet rr-places__go"
                  disabled={busy}
                  onClick={() => act({ action: "go", target: v.id, args: {}, text: "" })}
                >
                  {v.label}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

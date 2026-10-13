/**
 * A dating profile as a deck shows it (`deck.<app>.card`, spec §8): the
 * facts the card carries and nothing else. It renders only the fields it
 * names -- never a spread of the card -- so a value the server one day sent
 * by mistake would still never reach the screen (tests: phone-deck).
 *
 * Photos are procedural tiles carrying their caption (spec §13.5): a dating
 * card's photos have no generated image in v0.22.0.
 */
import React, { useState } from "react";

import { tileStyle } from "../phone/format.js";

export function PhotoTile({ pid, photo, index, children }) {
  return (
    <figure className="rr-photo" style={tileStyle(pid, index)}>
      <figcaption className="rr-photo__caption">{photo.caption}</figcaption>
      {children}
    </figure>
  );
}

export function Facts({ card }) {
  const line = [card.job, card.neighbourhood].filter(Boolean).join(" · ");
  return (
    <div className="rr-facts">
      <h3 className="rr-facts__name">
        {card.name}
        {card.age ? <span className="rr-facts__age">, {card.age}</span> : null}
      </h3>
      {line && <p className="rr-facts__line">{line}</p>}
      {card.shared && <p className="rr-facts__shared">{card.shared}</p>}
    </div>
  );
}

export function Hobbies({ hobbies }) {
  if (!hobbies || !hobbies.length) return null;
  return (
    <ul className="rr-chips" aria-label="Hobbies">
      {hobbies.map((h) => (
        <li key={h} className="rr-chip">
          {h}
        </li>
      ))}
    </ul>
  );
}

/** Matchstick's card: one photo at a time (tap for the next), the facts, the bio. */
export default function ProfileCard({ card }) {
  const photos = card.photos || [];
  const [shown, setShown] = useState(0);
  const at = photos.length ? shown % photos.length : 0;
  const photo = photos[at];
  return (
    <article className="rr-card" aria-label={`${card.name}, profile`}>
      {photo && (
        <button
          type="button"
          className="rr-card__photo"
          aria-label={photos.length > 1 ? "Next photo" : "Photo"}
          onClick={() => setShown((n) => (n + 1) % photos.length)}
        >
          <PhotoTile pid={card.pid} photo={photo} index={at} />
          {photos.length > 1 && (
            <span className="rr-card__dots" aria-hidden="true">
              {photos.map((p, i) => (
                <span key={p.id} className={i === at ? "is-on" : ""} />
              ))}
            </span>
          )}
        </button>
      )}
      <Facts card={card} />
      {card.bio && <p className="rr-card__bio">{card.bio}</p>}
      <Hobbies hobbies={card.hobbies} />
      {card.also_on && card.also_on.length > 0 && <p className="rr-card__also">Also on {card.also_on.join(", ")}</p>}
    </article>
  );
}

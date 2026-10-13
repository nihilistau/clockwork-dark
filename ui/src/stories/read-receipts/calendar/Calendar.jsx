/**
 * The Calendar app (spec §14, §18.2): your meet-ups, the ones coming first,
 * from the payload's `calendar` -- where, when, who, and how it stands. On
 * the day a planned one offers Go (`meet {do: go}`); until it is over it
 * can be called off (`meet {do: cancel}`, after a confirm). Past ones keep
 * their outcome line. Never the odds of anyone turning up.
 */
import React from "react";

import { MeetCard } from "../thread/RequestCard.jsx";

const UPCOMING = ["agreed", "due", "going"];

export default function Calendar({ phone, act, pending = null, onOpenContact = null }) {
  const rows = phone.calendar || [];
  const coming = rows.filter((m) => UPCOMING.includes(m.status));
  const past = rows.filter((m) => !UPCOMING.includes(m.status)).reverse();
  const group = (list) => (
    <ul className="rr-cal">
      {list.map((m) => (
        <li key={m.id} className="rr-cal__item">
          <p className="rr-cal__who">
            {onOpenContact ? (
              <button type="button" className="rr-cal__name" onClick={() => onOpenContact(m.pid)}>
                With {m.name}
              </button>
            ) : (
              <span className="rr-cal__name">With {m.name}</span>
            )}
          </p>
          {/* MeetCard is a list item (the thread draws it in its list), so it gets a list of its own. */}
          <ul className="rr-cal__one">
            <MeetCard meet={m} act={act} pending={pending} />
          </ul>
        </li>
      ))}
    </ul>
  );
  return (
    <section className="rr-app rr-app--calendar" aria-label="Calendar">
      <h2 className="rr-app__title" tabIndex={-1}>Calendar</h2>
      <div className="rr-app__body">
        <h3 className="rr-contact__head">Coming up</h3>
        {coming.length ? group(coming) : <p className="rr-card__sub rr-games__none">Nothing planned. Ask someone to meet from their contact card.</p>}
        {past.length > 0 && (
          <>
            <h3 className="rr-contact__head">Before</h3>
            {group(past)}
          </>
        )}
      </div>
    </section>
  );
}

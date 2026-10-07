/**
 * The people here, with their faces once met (v0.21.0, spec §4.4).
 *
 * `GET /api/people` (`engine/scenes/default_api.py::people_here`): rows of
 * {key, known, name, role_label, activity, portrait} and a `more` count --
 * no NPC id ever arrives, so none is ever rendered. A stranger (`known`
 * false) is a silhouette and a role: its name and portrait arrive empty, and
 * nothing here keys on, or shows, anything else of theirs. `key` is the
 * route's opaque per-response index, used only as the React key. Fetched on
 * mount and when the place, the hour or the turn moves; a stale list stays
 * up until the fresh one lands; a failed fetch renders nothing. In the
 * ledger it is a column, in the stage a strip.
 */
import React, { useEffect, useState } from "react";

import { fetchPeople } from "../api.js";

function Face({ person }) {
  if (person.known && person.portrait) {
    return <img className="people__portrait" src={person.portrait} alt={person.name} loading="lazy" />;
  }
  return (
    <span className="people__monogram" aria-hidden="true">
      {person.known && person.name ? person.name.trim().charAt(0) : (
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.4">
          <circle cx="12" cy="8.5" r="3.6" />
          <path d="M4.5 20c1-4 4-6 7.5-6s6.5 2 7.5 6" />
        </svg>
      )}
    </span>
  );
}

export default function PeopleStrip({ state, region = "stage" }) {
  const sessionId = state?.sessionId || "";
  const world = state?.world || {};
  // The answer and the session it was fetched for: another run's people are
  // never shown while this run's are on the way (T9 review finding 4).
  const [answer, setAnswer] = useState(null);

  useEffect(() => {
    if (!sessionId) return undefined;
    let live = true;
    fetchPeople(sessionId).then((data) => {
      if (live) setAnswer({ sessionId, data });
    });
    return () => {
      live = false;
    };
  }, [sessionId, world.location_id, world.world_hour, world.turn_number]);

  const current = answer && answer.sessionId === sessionId ? answer.data : null;
  const rows = current?.people || [];
  const more = current?.more || 0;
  if (rows.length === 0 && more === 0) return null;

  return (
    <section className={`people people--${region}`} aria-labelledby="panel-people-title">
      <h2 className="visually-hidden" id="panel-people-title" tabIndex={-1}>Here</h2>
      <ul className="people__list">
        {rows.map((person) => (
          <li key={person.key} className="people__card">
            <Face person={person} />
            <span className="people__who">{person.known ? person.name : person.role_label}</span>
            {person.activity && (
              <span className="people__doing" title={person.activity}>{person.activity}</span>
            )}
          </li>
        ))}
        {more > 0 && <li className="people__more">+{more} more</li>}
      </ul>
    </section>
  );
}

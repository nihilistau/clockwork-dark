/**
 * The village notice board.
 *
 * Server half has been live at GET /api/notices since the board was wired.
 * This is the missing client: what is posted here, what is posted elsewhere
 * (a reason to travel), and a button that takes a shift as an ordinary turn.
 * The engine's `work` skill is the only writer of gold and hours.
 */
import React, { useEffect, useState } from "react";
import Modal from "@core/parts/Modal.jsx";
import { fetchNotices } from "@core/api.js";

function Notice({ row, busy, onTake }) {
  const wage = Number(row.expected_wage) || 0;
  return (
    <li className="notice">
      <div className="notice__head">
        <h3 className="notice__title">{row.name}</h3>
        {wage > 0 && <span className="notice__wage">{wage}c</span>}
      </div>
      {row.blurb && <p className="notice__blurb">{row.blurb}</p>}
      <p className="notice__meta">
        {row.hours ? `${row.hours}h` : ""}
        {row.skill ? ` · ${row.skill}` : ""}
        {row.difficulty ? ` · ${row.difficulty}` : ""}
      </p>
      <button
        type="button"
        className="btn btn--sm"
        disabled={busy}
        onClick={() => onTake(row)}
      >
        Take the work
      </button>
    </li>
  );
}

export default function Notices({ sessionId, busy, onAct, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!sessionId) {
      setData({ notices: [], elsewhere: [] });
      return undefined;
    }
    let live = true;
    fetchNotices(sessionId)
      .then((next) => live && setData(next))
      .catch(() => live && setError("The board is rain-stuck and unreadable."));
    return () => {
      live = false;
    };
  }, [sessionId]);

  const here = data?.notices || [];
  const elsewhere = data?.elsewhere || [];

  return (
    <Modal title="Notice board" onClose={onClose}>
      {error && <p className="overlay__error">{error}</p>}
      {!data && !error && <p className="overlay__empty">Reading the pins…</p>}

      {data && (
        <>
          <p className="overlay__kicker">
            {data.location_name || "Here"}
            {data.shifts_per_day
              ? ` · ${data.shifts_worked_today || 0} of ${data.shifts_per_day} shifts today`
              : ""}
          </p>

          {here.length === 0 ? (
            <p className="overlay__empty">
              Nothing posted here that you can take right now.
            </p>
          ) : (
            <ul className="notice__list">
              {here.map((row) => (
                <Notice
                  key={row.id}
                  row={row}
                  busy={busy}
                  onTake={(job) => onAct(`Take the ${job.name} work posted on the board`)}
                />
              ))}
            </ul>
          )}

          {elsewhere.length > 0 && (
            <section className="notice__away">
              <h3 className="notice__away-head">Posted elsewhere</h3>
              <ul className="notice__list">
                {elsewhere.map((row) => (
                  <li key={row.id} className="notice notice--away">
                    <span className="notice__title">{row.name}</span>
                    <span className="notice__meta">
                      {String(row.location_id || "").replace(/_/g, " ")}
                      {row.hiring === false ? " · not hiring" : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </Modal>
  );
}

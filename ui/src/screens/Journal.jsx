/**
 * The quest journal.
 *
 * Objective lines come from the server, which reads them out of
 * QuestEngine.active_objectives — the same text the Storyteller is given. A
 * journal that paraphrases the prompt is a journal that eventually disagrees
 * with it, and the player has no way to tell which one is lying.
 *
 * The arc is shown as prominently as the quests. "A Quiet Life" is a complete
 * way to play, and a journal that only lists errands implies otherwise.
 */
import React, { useEffect, useState } from "react";
import Modal from "../parts/Modal.jsx";
import { fetchQuests } from "../api.js";

const STATUS_WORD = {
  active: "in hand",
  completed: "done",
  failed: "lost",
};

function Quest({ quest }) {
  const stages = Number(quest.stage_count) || 0;
  return (
    <li className="quest" data-status={quest.status}>
      <div className="quest__head">
        <h3 className="quest__title">{quest.title}</h3>
        <span className="quest__status">{STATUS_WORD[quest.status] || quest.status}</span>
      </div>

      {quest.objective ? (
        <p className="quest__objective">{quest.objective}</p>
      ) : (
        quest.summary && <p className="quest__summary">{quest.summary}</p>
      )}

      <p className="quest__meta">
        {quest.arc_title || quest.arc}
        {stages > 0 && ` · step ${Math.min(quest.stage_index + 1, stages)} of ${stages}`}
        {quest.started_day > 0 && ` · began day ${quest.started_day}`}
      </p>

      {stages > 0 && (
        <div className="quest__pips" aria-hidden="true">
          {Array.from({ length: stages }, (_, i) => (
            <span key={i} className={`quest__pip ${i <= quest.stage_index ? "is-done" : ""}`} />
          ))}
        </div>
      )}
    </li>
  );
}

export default function Journal({ sessionId, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    fetchQuests(sessionId)
      .then((next) => live && setData(next))
      .catch(() => live && setError("The journal pages are stuck together."));
    return () => {
      live = false;
    };
  }, [sessionId]);

  const quests = data?.quests || [];
  const open = quests.filter((q) => q.status === "active");
  const closed = quests.filter((q) => q.status !== "active");

  return (
    <Modal title="Journal" onClose={onClose}>
      {error && <p className="overlay__error">{error}</p>}
      {!data && !error && <p className="overlay__empty">Turning pages…</p>}

      {data && (
        <>
          <section className="journal__arc">
            <p className="overlay__kicker">Where this is going</p>
            <h3 className="journal__arc-title">{data.active_arc_title || data.active_arc}</h3>
            {data.active_arc_blurb && (
              <p className="journal__arc-blurb">{data.active_arc_blurb}</p>
            )}
          </section>

          <p className="overlay__kicker">In hand</p>
          {open.length === 0 && (
            <p className="overlay__empty">
              Nothing is owed and nothing is owing. That is allowed.
            </p>
          )}
          <ul className="quests">
            {open.map((quest) => (
              <Quest key={quest.id} quest={quest} />
            ))}
          </ul>

          {closed.length > 0 && (
            <>
              <p className="overlay__kicker">Behind you</p>
              <ul className="quests">
                {closed.map((quest) => (
                  <Quest key={quest.id} quest={quest} />
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </Modal>
  );
}

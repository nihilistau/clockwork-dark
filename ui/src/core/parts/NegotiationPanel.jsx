/**
 * What the two agents settled, for the author rather than for the player.
 *
 * DEBUG-SHAPED ON PURPOSE, which is why it is collapsed by default and why it
 * prints agent ids and rule names verbatim. `docs/GOVERNANCE.md` carried this
 * as a NOT WIRED row reading "the player currently has no way to know a second
 * agent won, lost or gave something up" -- and the honest answer to the player
 * half was never a table. The player gets the concession in the PROSE (the
 * narrator is handed it now) plus a margin mark on the log entry. This is the
 * other half: the tuning surface for whoever is writing the rule table.
 *
 * The payload has ridden every turn since the pipeline shipped with no reader
 * at all. Shape is engine/agents/pipeline.py's `PipelineResult.to_dict()`.
 *
 * `private` is never in it -- the pipeline drops it before the dict is built,
 * because this same structure is logged and sent to telemetry. If a motive
 * ever appears here, that is the bug, not this panel.
 *
 * Renders nothing at all when no pipeline ran, which is every turn of the
 * flagship and of any story declaring fewer than two participants.
 */
import React, { useState } from "react";

/** `private_scene_finishes` -> `private scene finishes`. */
function pretty(id) {
  return String(id || "").replace(/_/g, " ");
}

export default function NegotiationPanel({ negotiation }) {
  const [open, setOpen] = useState(false);

  if (!negotiation || !negotiation.ran) return null;

  const resolutions = negotiation.resolutions || [];
  const yielded = resolutions.filter((r) => r && r.loser);
  const beats = negotiation.beats || [];
  const refused = negotiation.refused || [];

  return (
    <section className={`negotiation ${open ? "is-open" : "is-collapsed"}`}>
      <button
        type="button"
        className="negotiation__toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="negotiation__label">
          {yielded.length > 0
            ? `${pretty(negotiation.lead)} led; ${yielded.length} gave way`
            : `${pretty(negotiation.lead)} led, uncontested`}
        </span>
        <span className="negotiation__chevron" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
      </button>

      {open && (
        <div className="negotiation__body">
          {yielded.length > 0 && (
            <dl className="negotiation__rules">
              {yielded.map((r, i) => (
                <div className="negotiation__rule" key={`${r.rule}-${r.loser}-${i}`}>
                  <dt>
                    {pretty(r.loser)} → {pretty(r.winner)}
                  </dt>
                  {/* The reason the AUTHOR wrote for this rule, which is the
                      thing worth reading here and the same string the narrator
                      is given. */}
                  <dd>{r.detail || pretty(r.rule)}</dd>
                </div>
              ))}
            </dl>
          )}

          {beats.length > 0 && (
            <ol className="negotiation__beats">
              {beats.map((beat, i) => (
                <li key={i}>{beat}</li>
              ))}
            </ol>
          )}

          {negotiation.blocked && (
            <p className="negotiation__blocked">
              Blocked{negotiation.block_reason ? `: ${negotiation.block_reason}` : ""}
            </p>
          )}

          {refused.length > 0 && (
            <p className="negotiation__refused">Refused: {refused.join(", ")}</p>
          )}

          {negotiation.veto && <p className="negotiation__blocked">Vetoed: {negotiation.veto}</p>}
        </div>
      )}
    </section>
  );
}

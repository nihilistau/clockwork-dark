/**
 * The Calendar app (v0.23.0 spec §9, §14.2): "Coming up", in words. A plan has no set time, so there is no
 * grid and no date to keep -- only what is open between you and someone: a plan to meet ("Drinks at The
 * Anchor, tonight") and a promise to message ("Kai will message you in the morning" / "You'll message Kai
 * tonight"), from the payload's `plans` and `promises` sections, soonest first. A promise that has been kept
 * or broken is listed once under "Before", with how it ended. Never the odds of anyone turning up.
 */
import React from "react";

import { humanize } from "../phone/format.js";

/** A promise's line: who is to message whom, and when, in the engine's words. */
export function promiseLine(p) {
  return p.by === "player"
    ? `You'll message ${p.name} ${p.window_words}`
    : `${p.name} will message you ${p.window_words}`;
}

const ENDED = { kept: "Kept", broken: "Broken", void: "Let go" };

function Row({ who, pid, line, sub = "", onOpenContact, testId }) {
  return (
    <li className="rr-cal__item" data-testid={testId}>
      <p className="rr-cal__who">
        {onOpenContact && pid ? (
          <button type="button" className="rr-cal__name" onClick={() => onOpenContact(pid)}>
            With {who}
          </button>
        ) : (
          <span className="rr-cal__name">With {who}</span>
        )}
      </p>
      <p className="rr-card__line">{line}</p>
      {sub && <p className="rr-card__sub">{sub}</p>}
    </li>
  );
}

export default function Calendar({ phone, onOpenContact = null }) {
  const plans = phone.plans || [];
  const promises = phone.promises || [];
  const open = promises.filter((p) => p.status === "open");
  const closed = promises.filter((p) => p.status !== "open");
  return (
    <section className="rr-app rr-app--calendar" aria-label="Calendar">
      <h2 className="rr-app__title" tabIndex={-1}>Calendar</h2>
      <div className="rr-app__body">
        <h3 className="rr-contact__head">Coming up</h3>
        {plans.length + open.length === 0 ? (
          <p className="rr-card__sub rr-games__none">Nothing planned. Ask someone to meet from their chat.</p>
        ) : (
          <ul className="rr-cal">
            {plans.map((pl) => (
              <Row key={pl.id} who={pl.name} pid={pl.pid} line={pl.words} onOpenContact={onOpenContact} testId={`plan-${pl.id}`} />
            ))}
            {open.map((p) => (
              <Row
                key={p.id}
                who={p.name}
                pid={p.pid}
                line={promiseLine(p)}
                sub={p.opens_at_words && p.opens_at_words !== "now" ? `From ${p.opens_at_words}` : ""}
                onOpenContact={onOpenContact}
                testId={`promise-${p.id}`}
              />
            ))}
          </ul>
        )}
        {closed.length > 0 && (
          <>
            <h3 className="rr-contact__head">Before</h3>
            <ul className="rr-cal">
              {closed.map((p) => (
                <Row
                  key={p.id}
                  who={p.name}
                  pid={p.pid}
                  line={promiseLine(p)}
                  sub={ENDED[p.status] || humanize(p.status)}
                  onOpenContact={onOpenContact}
                  testId={`promise-${p.id}`}
                />
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}

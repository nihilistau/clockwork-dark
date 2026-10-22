/**
 * A person's contact card (spec §18.2): their photos and profile as their
 * dating app shows it, where things stand -- the stage's words and the
 * closeness band, never a number -- "Getting closer" when the engine's
 * `hints` say so, what they have told you of their days, whether you could
 * ask for their number and the engine's words for why not, the promises and
 * plans open between you (`promises`, `plans`), "Your story" (the engine's
 * history lines), what they have chosen to tell you (their `canon`, never
 * what they know of you), and what you can do: message them, ask to meet
 * (the plan sheet), start a game, and unmatch, end things or block, each
 * behind a confirm.
 *
 * Everything is the payload's `contacts` row (engine/social/relationships.py)
 * and every action a `phone_action` (rule 1): whether they say yes to a
 * meet-up or a game is the engine's, told back in words.
 *
 * At 1200px wide and over it opens as a side sheet beside the phone
 * (spec §18.3, `sheet`), the thread staying on screen.
 */
import React, { useEffect, useRef, useState } from "react";

import { Hobbies, PhotoTile } from "../apps/ProfileCard.jsx";
import Avatar from "../phone/Avatar.jsx";
import Confirm from "../phone/Confirm.jsx";
import { humanize, stampOf } from "../phone/format.js";
import { GAME_WORDS } from "../thread/media.js";
import { promiseLine } from "../calendar/Calendar.jsx";
import { venuesOf } from "../thread/Thread.jsx";
import PlanSheet from "./PlanSheet.jsx";

/** The confirms: what each does, in the player's words, and the action it sends. */
export const ENDINGS = {
  unmatch: {
    label: "Unmatch",
    ask: (name) => `Unmatch ${name}? Your chat on the app closes for both of you.`,
  },
  end: {
    label: "End things",
    ask: (name) => `End things with ${name}? They'll know it's over.`,
  },
  block: {
    label: "Block",
    ask: (name) => `Block ${name}? They won't be able to reach you anywhere on the phone.`,
  },
};

/** "Heard from today", "3 days ago": whole in-game days since their last message. */
export function heardWords(days) {
  if (days == null) return "You haven't heard from them yet.";
  if (days === 0) return "Last heard from today.";
  if (days === 1) return "Last heard from yesterday.";
  return `Last heard from ${days} days ago.`;
}

export default function ContactCard({
  contact,
  phone,
  act,
  pending = null,
  onBack,
  onOpenThread = null,
  sheet = false,
}) {
  const [asking, setAsking] = useState(""); // "", "unmatch", "end", "block"
  const [planning, setPlanning] = useState(false);
  const [shown, setShown] = useState(0);
  const triggers = useRef({});
  const drawn = useRef(false);
  const lastAsked = useRef("");
  // Focus returns to the button that opened a confirm when it closes without acting.
  useEffect(() => {
    if (!drawn.current) {
      drawn.current = true;
      return;
    }
    if (!asking && lastAsked.current) triggers.current[lastAsked.current]?.focus?.();
    lastAsked.current = asking;
  }, [asking]);

  if (!contact) {
    return (
      <section className="rr-app rr-contact" aria-label="Contact">
        <header className="rr-thread__head">
          <button type="button" className="rr-back" aria-label="Back" onClick={onBack}>
            <span aria-hidden="true">‹</span>
          </button>
          <h2 className="rr-app__title" tabIndex={-1}>Contact</h2>
        </header>
        <p className="rr-empty">They're no longer in your phone.</p>
      </section>
    );
  }

  const name = contact.name;
  const profile = contact.profile || {};
  const photos = contact.photos || [];
  const at = photos.length ? shown % photos.length : 0;
  const busy = (action) => Boolean(pending && pending.action === action && pending.target === contact.pid);
  const threads = (phone.threads || []).filter((t) => (contact.thread_ids || []).includes(t.thread_id));
  const open = threads.find((t) => t.open !== false) || threads[0] || null;
  // What the engine lets the player see of how things stand: words and booleans (the `hints` section).
  const hint = (phone.hints && phone.hints[contact.pid]) || null;
  const number = hint && hint.number ? hint.number : null;
  const promises = (phone.promises || []).filter((p) => p.pid === contact.pid && p.status === "open");
  const plans = (phone.plans || []).filter((p) => p.pid === contact.pid);
  const now = phone.now;
  const facts = [profile.age ? String(profile.age) : "", profile.job, profile.neighbourhood].filter(Boolean).join(" · ");
  const games = Object.keys(GAME_WORDS);
  const doEnd = (what) => {
    setAsking("");
    lastAsked.current = "";
    act({ action: what, target: contact.pid, args: {}, text: "" });
  };
  const ask = (what) => (el) => {
    triggers.current[what] = el;
  };

  return (
    <section className={`rr-app rr-contact${sheet ? " rr-contact--sheet" : ""}`} aria-label={`${name}, contact card`} data-testid={`contact-${contact.pid}`}>
      <header className="rr-thread__head">
        <button type="button" className="rr-back" aria-label={sheet ? "Close" : "Back"} onClick={onBack}>
          <span aria-hidden="true">{sheet ? "×" : "‹"}</span>
        </button>
        <Avatar pid={contact.pid} name={name} url={contact.avatar_url} size="sm" />
        <h2 className="rr-app__title rr-contact__name" tabIndex={-1}>
          {name}
        </h2>
      </header>
      <div className="rr-app__body rr-contact__body">
        {photos.length > 0 && (
          <button
            type="button"
            className="rr-card__photo rr-contact__photo"
            aria-label={photos.length > 1 ? "Next photo" : "Photo"}
            onClick={() => setShown((n) => (n + 1) % photos.length)}
          >
            <PhotoTile pid={contact.pid} photo={photos[at]} index={at} />
            {photos.length > 1 && (
              <span className="rr-card__dots" aria-hidden="true">
                {photos.map((p, i) => (
                  <span key={p.id} className={i === at ? "is-on" : ""} />
                ))}
              </span>
            )}
          </button>
        )}
        <div className="rr-contact__where" data-testid="contact-stage">
          {contact.stage_words && <span className="rr-contact__stage">{contact.stage_words}</span>}
          {contact.band && <span className="rr-chip rr-contact__band">{humanize(contact.band)}</span>}
        </div>
        {hint && hint.closer_soon && (
          <p className="rr-contact__closer" data-testid="contact-closer">
            Getting closer
          </p>
        )}
        <p className="rr-card__sub">{heardWords(contact.last_heard_days)}</p>
        {hint && hint.available_words && <p className="rr-card__sub" data-testid="contact-available">{hint.available_words}</p>}
        {number && !number.ok && number.why && (
          <p className="rr-card__sub" data-testid="contact-number-why">
            Their number: {number.why}
          </p>
        )}
        {number && number.ok && <p className="rr-card__sub">You could ask for their number.</p>}
        {(promises.length > 0 || plans.length > 0) && (
          <ul className="rr-contact__open" data-testid="contact-open">
            {plans.map((pl) => (
              <li key={pl.id}>{pl.words}</li>
            ))}
            {promises.map((p) => (
              <li key={p.id}>{promiseLine(p)}</li>
            ))}
          </ul>
        )}
        {facts && <p className="rr-facts__line">{facts}</p>}
        {contact.matched_on && <p className="rr-card__sub">Matched on {contact.matched_on}</p>}
        {profile.bio && <p className="rr-card__bio">{profile.bio}</p>}
        <Hobbies hobbies={profile.hobbies} />
        {(profile.prompts || []).map((p) => (
          <div key={p.id} className="rr-prompt">
            <p className="rr-prompt__q">{p.q}</p>
            <p className="rr-prompt__a">{p.a}</p>
          </div>
        ))}

        <div className="rr-contact__actions">
          {open && onOpenThread && (
            <button type="button" className="rr-btn rr-btn--small" onClick={() => onOpenThread(open.thread_id)}>
              Message
            </button>
          )}
          {contact.open && open && (
            <button type="button" className="rr-btn rr-btn--small rr-btn--quiet" aria-expanded={planning} onClick={() => setPlanning((p) => !p)}>
              Ask to meet
            </button>
          )}
        </div>
        {planning && contact.open && open && (
          <PlanSheet
            pid={contact.pid}
            threadId={open.thread_id}
            venues={venuesOf(phone)}
            kinds={phone.meet_options && phone.meet_options.kinds}
            act={act}
            busy={Boolean(pending && pending.action === "ask" && pending.target === open.thread_id)}
            onDone={() => setPlanning(false)}
          />
        )}
        {contact.open && (
          <div className="rr-contact__games" role="group" aria-label="Start a game">
            {games.map((g) => (
              <button
                key={g}
                type="button"
                className="rr-btn rr-btn--small rr-btn--quiet"
                disabled={busy("game_invite")}
                onClick={() => act({ action: "game_invite", target: contact.pid, args: { game: g }, text: "" })}
              >
                Play {GAME_WORDS[g]}
              </button>
            ))}
          </div>
        )}

        <h3 className="rr-contact__head">Your story</h3>
        {(contact.history || []).length === 0 ? (
          <p className="rr-card__sub">Nothing yet.</p>
        ) : (
          <ol className="rr-story" data-testid="contact-story">
            {contact.history.map((h, i) => (
              <li key={`${h.at}-${i}`} className="rr-story__row">
                <span className="rr-story__when">{h.at != null ? stampOf(h.at, now) : `Day ${h.day}`}</span>
                <span className="rr-story__what">{h.text}</span>
              </li>
            ))}
          </ol>
        )}

        <h3 className="rr-contact__head">What you know about {name}</h3>
        {(contact.about || []).length === 0 ? (
          <p className="rr-card__sub">They haven't told you much yet.</p>
        ) : (
          <ul className="rr-about" data-testid="contact-about">
            {contact.about.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        )}

        <div className="rr-contact__endings">
          {asking ? (
            <Confirm
              label={`${ENDINGS[asking].label}?`}
              ask={ENDINGS[asking].ask(name)}
              yes={ENDINGS[asking].label}
              busy={busy(asking)}
              testId={`confirm-${asking}`}
              onYes={() => doEnd(asking)}
              onNo={() => setAsking("")}
            />
          ) : (
            <>
              {contact.matched && (
                <button ref={ask("unmatch")} type="button" className="rr-btn rr-btn--small rr-btn--quiet" onClick={() => setAsking("unmatch")}>
                  {ENDINGS.unmatch.label}
                </button>
              )}
              {contact.open && (
                <button ref={ask("end")} type="button" className="rr-btn rr-btn--small rr-btn--quiet" onClick={() => setAsking("end")}>
                  {ENDINGS.end.label}
                </button>
              )}
              <button ref={ask("block")} type="button" className="rr-btn rr-btn--small rr-btn--quiet rr-btn--warn" onClick={() => setAsking("block")}>
                {ENDINGS.block.label}
              </button>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

/**
 * The Settings app (spec §18.2):
 *
 * - your profile on each dating app: its bio, up to the payload's
 *   `settings.bio_max` (the engine's `social.max_text_chars`, 600)
 *   (`edit_profile {field: bio}` to that app);
 * - discovery (ages and distance), shown and NOT changeable during a run
 *   (v0.22.0: no phone action changes it -- docs/GOVERNANCE.md NOT WIRED,
 *   engine/social/intents.py);
 * - Natter's read receipts (`set_receipts {to: on|off}`);
 * - "Let time pass" (local mode only, a preference of this browser:
 *   settings/letTimePass.js), hidden when the payload's `auto_wait` is false.
 */
import React, { useEffect, useState } from "react";

import { humanize } from "../phone/format.js";
import { TEXT_MAX } from "../thread/ComposeBar.jsx";

function BioEditor({ app, bio, act, busy, max }) {
  const [text, setText] = useState(bio);
  useEffect(() => setText(bio), [bio]);
  const over = text.length > max;
  const id = `rr-bio-${app.id}`;
  return (
    <form
      className="rr-field rr-settings__bio"
      onSubmit={(e) => {
        e.preventDefault();
        if (!over && text !== bio) act({ action: "edit_profile", target: app.id, args: { field: "bio" }, text });
      }}
    >
      <label className="rr-field__label" htmlFor={id}>
        Your bio on {app.label}
      </label>
      <textarea id={id} className="rr-input rr-input--area" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
      <p className={`rr-count${over ? " is-over" : ""}`} aria-live={text.length > max - 100 ? "polite" : "off"}>
        {text.length}/{max}
      </p>
      <div className="rr-card__actions">
        <button type="submit" className="rr-btn rr-btn--small" disabled={busy || over || text === bio}>
          Save
        </button>
      </div>
    </form>
  );
}

function Switch({ label, on, onChange, disabled = false, testId }) {
  return (
    <label className="rr-switch">
      <span className="rr-switch__label">{label}</span>
      <input type="checkbox" role="switch" checked={on} disabled={disabled} onChange={(e) => onChange(e.target.checked)} data-testid={testId} />
    </label>
  );
}

export default function Settings({ phone, act, pending = null, letTimePass = false, onLetTimePass = () => {} }) {
  const player = phone.player || {};
  const bios = player.bios || {};
  const dating = (phone.apps || []).filter((a) => a.kind === "dating");
  const discovery = player.discovery || {};
  const receipts = !(phone.settings && phone.settings.receipts === false);
  // The engine's cap on an edit_profile text (`social.max_text_chars`), as the payload states it.
  const bioMax = Number(phone.settings && phone.settings.bio_max) > 0 ? Number(phone.settings.bio_max) : TEXT_MAX;
  const busy = (action) => Boolean(pending && pending.action === action);
  const natter = (phone.apps || []).find((a) => a.id === "natter");
  return (
    <section className="rr-app rr-app--settings" aria-label="Settings">
      <h2 className="rr-app__title" tabIndex={-1}>Settings</h2>
      <div className="rr-app__body rr-settings">
        <h3 className="rr-contact__head">Profiles</h3>
        {dating.map((app) => (
          <BioEditor key={app.id} app={app} bio={String(bios[app.id] || "")} act={act} busy={busy("edit_profile")} max={bioMax} />
        ))}

        <h3 className="rr-contact__head">Discovery</h3>
        <dl className="rr-settings__list" data-testid="discovery">
          <dt>Ages</dt>
          <dd>
            {discovery.age_min != null && discovery.age_max != null ? `${discovery.age_min}–${discovery.age_max}` : "Any"}
          </dd>
          <dt>Distance</dt>
          <dd>{discovery.distance ? humanize(discovery.distance) : "Anywhere"}</dd>
        </dl>
        <p className="rr-card__sub">Who you see is set when you set up the phone. It can't be changed during a run.</p>

        {natter && (
          <>
            <h3 className="rr-contact__head">{natter.label}</h3>
            <Switch
              label="Read receipts"
              on={receipts}
              disabled={busy("set_receipts")}
              testId="receipts"
              onChange={(on) => act({ action: "set_receipts", target: natter.id, args: { to: on ? "on" : "off" }, text: "" })}
            />
            <p className="rr-card__sub">With them off, people on {natter.label} don't see when you've read their messages, and you don't see when they've read yours.</p>
          </>
        )}

        {phone.auto_wait === true && (
          <>
            <h3 className="rr-contact__head">Time</h3>
            <Switch label="Let time pass" on={letTimePass} testId="let-time-pass" onChange={onLetTimePass} />
            <p className="rr-card__sub">
              When someone is typing and you leave the chat alone for 30 seconds, the phone lets 15 minutes pass. Kept in this browser
              only.
            </p>
          </>
        )}
      </div>
    </section>
  );
}

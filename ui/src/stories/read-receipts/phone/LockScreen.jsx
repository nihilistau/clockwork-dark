/**
 * The lock screen (spec §15.3, §18.2): the time, what the phone has to say
 * (a new run's opening, or "While you were away: ..." after a resume), the
 * notifications newest first, "Put it down" -- the `wait` action, time
 * passing until the next thing happens -- and a way into the phone.
 */
import React from "react";

import { appLabel } from "./apps.js";
import { clockOf, stampOf } from "./format.js";

export default function LockScreen({ phone, lock, act, pending, onUnlock, onOpenThread }) {
  const now = phone.now;
  const rows = [...(phone.notifications || [])].reverse();
  const waiting = Boolean(pending && pending.action === "wait");
  return (
    <div className="rr-lock" data-testid="lock-screen">
      <div className="rr-lock__clock">
        <span className="rr-lock__time">{clockOf(now)}</span>
        <span className="rr-lock__date">{now ? `${now.weekday} · Day ${now.day}` : ""}</span>
      </div>
      {lock && lock.text && <p className="rr-lock__note">{lock.text}</p>}
      <ol className="rr-lock__list" aria-label="Notifications">
        {rows.length === 0 && <li className="rr-lock__empty">No notifications</li>}
        {rows.map((n) => (
          <li key={n.id}>
            <button
              type="button"
              className="rr-notif"
              data-testid={`notif-${n.id}`}
              onClick={() => (n.thread_id ? onOpenThread(n.thread_id) : onUnlock())}
            >
              <span className="rr-notif__head">
                <span className="rr-notif__app">{appLabel(phone, n.app)}</span>
                <span className="rr-notif__at">{stampOf(n.at, now)}</span>
              </span>
              <span className="rr-notif__name">{n.name}</span>
              <span className="rr-notif__preview">{n.preview}</span>
            </button>
          </li>
        ))}
      </ol>
      <div className="rr-lock__actions">
        <button
          type="button"
          className="rr-btn rr-btn--quiet"
          disabled={waiting}
          onClick={() => act({ action: "wait", target: "", args: { until: "next" }, text: "" })}
        >
          {waiting ? "Waiting…" : "Put it down"}
        </button>
        <button type="button" className="rr-btn rr-lock__open" onClick={onUnlock}>
          Open phone
        </button>
      </div>
    </div>
  );
}

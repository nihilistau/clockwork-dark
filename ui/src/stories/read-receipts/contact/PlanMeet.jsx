/**
 * Plan a meet-up (spec §14.1, §7.1's `propose_meet {venue, day, slot}`):
 * a place, a day one to seven days ahead, and a time of day -- the choices
 * the payload's `meet_options` lists (venues.yaml, relationships.yaml
 * `meets:`). The engine answers at once: yes (a Calendar row), another time,
 * or not yet -- told in the thread, in words.
 */
import React, { useState } from "react";

import { humanize } from "../phone/format.js";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const pad = (n) => String(n).padStart(2, "0");

/** "Tomorrow (Wed)", "Thu", ...: `ahead` days after `now` (the payload's {day, weekday}). */
export function dayWords(now, ahead) {
  const at = WEEKDAYS.indexOf(now && now.weekday);
  const weekday = at >= 0 ? WEEKDAYS[(at + ahead) % 7] : `Day ${(Number(now && now.day) || 1) + ahead}`;
  return ahead === 1 ? `Tomorrow (${weekday})` : weekday;
}

/** "Evening, 19:00": a slot's id in words and its start hour. */
export function slotWords(slot) {
  const hour = Number(slot.start) || 0;
  return `${humanize(slot.id)}, ${pad(Math.floor(hour))}:${pad(Math.round((hour % 1) * 60))}`;
}

export default function PlanMeet({ contact, options, now, act, busy = false, onDone }) {
  const venues = (options && options.venues) || [];
  const slots = (options && options.slots) || [];
  const [first, last] = (options && options.days) || [1, 7];
  const days = [];
  for (let d = Number(first) || 1; d <= (Number(last) || 7); d += 1) days.push(d);
  const [venue, setVenue] = useState(venues[0] ? venues[0].id : "");
  const [day, setDay] = useState(days[0] || 1);
  const [slot, setSlot] = useState(slots[0] ? slots[0].id : "");
  if (!venues.length || !slots.length) return <p className="rr-card__sub">There's nowhere to meet yet.</p>;
  const send = () => {
    act({ action: "propose_meet", target: contact.pid, args: { venue, day: Number(day), slot }, text: "" });
    onDone && onDone();
  };
  return (
    <form
      className="rr-plan"
      aria-label={`Plan a meet-up with ${contact.name}`}
      onSubmit={(e) => {
        e.preventDefault();
        send();
      }}
    >
      <label className="rr-field">
        <span className="rr-field__label">Where</span>
        <select className="rr-input" value={venue} onChange={(e) => setVenue(e.target.value)} data-testid="plan-venue">
          {venues.map((v) => (
            <option key={v.id} value={v.id}>
              {v.place || v.label}
              {v.neighbourhood ? ` · ${v.neighbourhood}` : ""}
            </option>
          ))}
        </select>
      </label>
      <label className="rr-field">
        <span className="rr-field__label">Day</span>
        <select className="rr-input" value={day} onChange={(e) => setDay(Number(e.target.value))} data-testid="plan-day">
          {days.map((d) => (
            <option key={d} value={d}>
              {dayWords(now, d)}
            </option>
          ))}
        </select>
      </label>
      <label className="rr-field">
        <span className="rr-field__label">When</span>
        <select className="rr-input" value={slot} onChange={(e) => setSlot(e.target.value)} data-testid="plan-slot">
          {slots.map((s) => (
            <option key={s.id} value={s.id}>
              {slotWords(s)}
            </option>
          ))}
        </select>
      </label>
      <div className="rr-card__actions">
        <button type="submit" className="rr-btn rr-btn--small" disabled={busy}>
          Ask {contact.name}
        </button>
        <button type="button" className="rr-btn rr-btn--small rr-btn--quiet" onClick={onDone}>
          Not now
        </button>
      </div>
    </form>
  );
}

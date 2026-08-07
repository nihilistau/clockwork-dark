/**
 * Character sheet.
 *
 * The old panel showed four rows and a flat inventory list. Everything here
 * beyond that was already being serialized by the server and thrown away by
 * the client: wounds, hunger, reputation, archetype.
 */
import React from "react";
import { prettyPlace } from "./Chrome.jsx";

function Meter({ label, value, max, tone }) {
  const pct = max ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div className="meter" data-tone={tone}>
      <div className="meter__row">
        <span className="meter__label">{label}</span>
        <span className="meter__value">
          {value}
          {max ? <span className="meter__max">/{max}</span> : null}
        </span>
      </div>
      <div className="meter__track" role="presentation">
        <div className="meter__fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function Line({ label, value }) {
  return (
    <div className="statline">
      <span className="statline__label">{label}</span>
      <span className="statline__value">{value}</span>
    </div>
  );
}

export default function Sheet({ world }) {
  if (!world) return <aside className="sheet" aria-label="Character" />;

  const stats = world.stats || {};
  const wounds = world.wounds || [];
  const reputations = Object.entries(world.reputations || {});

  return (
    <aside className="sheet" aria-label="Character">
      <h2 className="sheet__name">{world.player_name || "Traveler"}</h2>
      <p className="sheet__archetype">{world.archetype || "wayfarer"}</p>

      <Meter label="Health" value={stats.hp ?? 0} max={stats.max_hp ?? 20} tone="hp" />
      {/* Cap, not max: hunger lowers the real ceiling, and a bar drawn against
          max would read "full" while the player is quietly capped. */}
      <Meter
        label="Stamina"
        value={stats.stamina ?? 0}
        max={world.stamina_cap ?? stats.max_stamina ?? 100}
        tone="stamina"
      />
      {world.hunger_stage && world.hunger_stage !== "fed" && (
        <p className="sheet__condition" data-stage={world.hunger_stage}>
          {world.hunger_stage}
          {world.stamina_cap < (stats.max_stamina ?? 100) && (
            <span className="sheet__condition-note">
              {" "}— stamina capped at {world.stamina_cap}
            </span>
          )}
        </p>
      )}

      <div className="sheet__lines">
        <Line label="Gold" value={stats.gold ?? 0} />
        <Line label="Place" value={prettyPlace(world.location_id || "—")} />
      </div>

      {wounds.length > 0 && (
        <>
          <h3 className="sheet__heading">Wounds</h3>
          <ul className="wounds">
            {wounds.map((w) => (
              <li key={w.id} className="wounds__item">
                {w.text}
              </li>
            ))}
          </ul>
        </>
      )}

      <h3 className="sheet__heading">Carried</h3>
      <ul className="inventory">
        {(world.inventory || []).map((item) => (
          <li key={item.id} className="inventory__item">
            <span>{item.name}</span>
            <span className="inventory__qty">×{item.qty}</span>
          </li>
        ))}
        {(world.inventory || []).length === 0 && (
          <li className="inventory__empty">Nothing but what you stand in.</li>
        )}
      </ul>

      {reputations.length > 0 && (
        <>
          <h3 className="sheet__heading">Standing</h3>
          <div className="sheet__lines">
            {reputations.map(([faction, value]) => (
              <Line key={faction} label={prettyPlace(faction)} value={value > 0 ? `+${value}` : value} />
            ))}
          </div>
        </>
      )}
    </aside>
  );
}

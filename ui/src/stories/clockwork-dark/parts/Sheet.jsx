/**
 * Character sheet.
 *
 * The old panel showed four rows and a flat inventory list. Everything here
 * beyond that was already being serialized by the server and thrown away by
 * the client: wounds, hunger, reputation, archetype.
 */
import React, { useEffect, useState } from "react";
import { prettyPlace } from "@core/parts/Chrome.jsx";
import { fetchItems } from "@core/api.js";
import PaintFrame from "@core/parts/PaintFrame.jsx";

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

/**
 * item id -> picture, resolved once per session.
 *
 * The turn payload's inventory carries id/name/qty and nothing else, so the
 * only way to draw a carried thing is to ask the server what the art manifest
 * says. Refetched when the inventory changes, because a newly acquired item
 * is exactly the one the player wants to see.
 */
function useItemArt(sessionId, signature) {
  const [art, setArt] = useState({});
  useEffect(() => {
    if (!sessionId) return undefined;
    let live = true;
    fetchItems(sessionId)
      .then((data) => {
        if (!live) return;
        const map = {};
        for (const item of data.items || []) map[item.id] = item.image;
        setArt(map);
      })
      .catch(() => {
        /* no pictures is a worse sheet, not a broken one */
      });
    return () => {
      live = false;
    };
  }, [sessionId, signature]);
  return art;
}

export default function Sheet({ world, sessionId, onOpenPack }) {
  const inventory = world?.inventory || [];
  // A stable signature so the effect refires when the pack changes but not on
  // every unrelated turn.
  const art = useItemArt(sessionId, inventory.map((i) => `${i.id}:${i.qty}`).join(","));

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
      {/* A grid of paintings rather than a list of names. The full pack --
          description, weight, worth, actions, crafting -- is one click away
          in Inventory.jsx; this column is 220px and cannot hold it. */}
      <ul className="satchel">
        {inventory.map((item) => (
          <li key={item.id} className="satchel__item" title={item.name}>
            <PaintFrame size="square" className="satchel__art">
              {art[item.id] && (
                <img className="paint__img is-loaded" src={art[item.id]} alt="" loading="lazy" />
              )}
              {item.qty > 1 && <span className="satchel__qty">×{item.qty}</span>}
            </PaintFrame>
            <span className="satchel__name">{item.name}</span>
          </li>
        ))}
        {inventory.length === 0 && (
          <li className="inventory__empty">Nothing but what you stand in.</li>
        )}
      </ul>
      <button type="button" className="btn btn--sm btn--ghost sheet__packbtn" onClick={onOpenPack}>
        Open the pack
      </button>

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

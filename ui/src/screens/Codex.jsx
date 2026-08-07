/**
 * The Codex — Atlas, Souls, Things.
 *
 * Ported from Design_files/ui_kits/clockwork-world/{Atlas,Souls,Things}.jsx.
 * The mockups painted their tiles with inline hex; here the same structure is
 * driven by real art from data/art/manifest.yaml (resolved server-side, since
 * the browser cannot read the manifest) and styled from semantic tokens so the
 * four [data-phase] themes reach it.
 *
 * Discovery gating is applied where the engine actually knows the answer —
 * places you have stood in, people the story ledger says you have met. Where
 * it does not know, everything shows: a codex that hides the item table
 * teaches the player nothing and protects no secret.
 */
import React, { useEffect, useState } from "react";
import Modal from "../parts/Modal.jsx";
import { fetchPlaces, fetchSouls, fetchThings } from "../api.js";

const TABS = [
  { id: "places", label: "Atlas", loader: fetchPlaces, pick: (d) => d.places || [] },
  { id: "souls", label: "Souls", loader: fetchSouls, pick: (d) => d },
  { id: "things", label: "Things", loader: fetchThings, pick: (d) => d.things || [] },
];

function Plate({ src, alt, ratio = "16 / 9" }) {
  return (
    <div className="plate" style={{ aspectRatio: ratio }}>
      {src ? (
        <img className="plate__img" src={src} alt={alt} loading="lazy" />
      ) : (
        <span className="plate__blank" aria-hidden="true" />
      )}
      <span className="plate__grain" aria-hidden="true" />
      <span className="plate__vignette" aria-hidden="true" />
    </div>
  );
}

function PlaceCard({ place }) {
  return (
    <article className={`codexcard ${place.discovered ? "" : "is-unknown"}`}>
      <Plate src={place.image} alt={place.discovered ? place.name : ""} />
      <div className="codexcard__body">
        <div className="codexcard__head">
          <h3 className="codexcard__name">{place.discovered ? place.name : "Unwalked"}</h3>
          {place.here && <span className="pill pill--brass">you are here</span>}
        </div>
        <p className="codexcard__note">
          {place.discovered
            ? `Ring ${place.ring}`
            : "You have not stood here. The map knows only that it is there."}
        </p>
        {place.discovered && place.roads.length > 0 && (
          <ul className="roads">
            {place.roads.map((road) => (
              <li key={road.to} className="roads__item">
                <span>{road.name}</span>
                <span className="roads__cost">
                  {road.hours > 0 ? `${road.hours} h` : "adjacent"}
                  {road.danger_dc > 0 ? ` · DC ${road.danger_dc}` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </article>
  );
}

function SoulCard({ soul }) {
  return (
    <article className={`codexcard ${soul.met ? "" : "is-unknown"}`}>
      <Plate src={soul.portrait} alt={soul.met ? soul.name : ""} ratio="3 / 4" />
      <div className="codexcard__body">
        <h3 className="codexcard__name">{soul.name}</h3>
        <p className="codexcard__role">
          {soul.role}
          {soul.place ? ` · ${soul.place}` : ""}
        </p>
        {soul.met ? (
          <>
            {soul.traits.length > 0 && (
              <div className="pills">
                {soul.traits.map((trait) => (
                  <span key={trait} className="pill">
                    {trait}
                  </span>
                ))}
              </div>
            )}
            <p className="codexcard__note">
              {soul.first_met_day > 0 ? `Met on day ${soul.first_met_day}. ` : ""}
              {/* Disposition is the ledger's number, not a hidden stat: the
                  player has earned every point of it in conversation. */}
              Regard {soul.disposition > 0 ? `+${soul.disposition}` : soul.disposition}
            </p>
          </>
        ) : (
          <p className="codexcard__note">A face you have not been close enough to keep.</p>
        )}
      </div>
    </article>
  );
}

function FormChip({ form }) {
  return (
    <div className={`formchip ${form.current ? "is-current" : ""}`}>
      <Plate src={form.portrait} alt={`The Assistant as ${form.form}`} ratio="1 / 1" />
      <span className="formchip__label">{form.form}</span>
      {form.current && <span className="formchip__now">now</span>}
    </div>
  );
}

function ThingTile({ thing }) {
  return (
    <div className={`thing ${thing.carried > 0 ? "is-carried" : ""}`}>
      <Plate src={thing.image} alt={thing.name} ratio="1 / 1" />
      <div className="thing__body">
        <span className="thing__name">{thing.name}</span>
        <span className="thing__meta">
          <span>{thing.from || "not for sale"}</span>
          {/* Prices are copper. The design brief is explicit that this world
              never floats gold coins in the air. */}
          <span className="thing__price">{thing.price > 0 ? `${thing.price}c` : "—"}</span>
        </span>
        {thing.carried > 0 && <span className="thing__carried">carried ×{thing.carried}</span>}
      </div>
    </div>
  );
}

export default function Codex({ sessionId, onClose }) {
  const [tab, setTab] = useState("places");
  const [payloads, setPayloads] = useState({});
  const [error, setError] = useState("");

  useEffect(() => {
    const entry = TABS.find((t) => t.id === tab);
    if (!entry || payloads[tab]) return undefined;
    let live = true;
    entry
      .loader(sessionId)
      .then((data) => live && setPayloads((prev) => ({ ...prev, [tab]: entry.pick(data) })))
      .catch(() => live && setError("That page of the codex is missing."));
    return () => {
      live = false;
    };
  }, [tab, sessionId, payloads]);

  const data = payloads[tab];

  return (
    <Modal title="Codex" onClose={onClose} wide>
      {/* Toggle buttons rather than role="tab". The full tab pattern owes the
          reader arrow-key roving focus and an id-linked tabpanel; a half-built
          one announces affordances that are not there. */}
      <div className="codextabs" role="group" aria-label="Codex sections">
        {TABS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            aria-pressed={tab === entry.id}
            className={`codextab ${tab === entry.id ? "is-active" : ""}`}
            onClick={() => setTab(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {error && <p className="overlay__error">{error}</p>}
      {!data && !error && <p className="overlay__empty">Reading…</p>}

      {data && tab === "places" && (
        <div className="codexgrid">
          {data.map((place) => (
            <PlaceCard key={place.id} place={place} />
          ))}
        </div>
      )}

      {data && tab === "souls" && (
        <>
          <p className="overlay__kicker">The living</p>
          <div className="codexgrid codexgrid--tight">
            {(data.souls || []).map((soul) => (
              <SoulCard key={soul.id} soul={soul} />
            ))}
          </div>
          <p className="overlay__kicker">The Assistant wears</p>
          <div className="formchips">
            {(data.forms || []).map((form) => (
              <FormChip key={form.form} form={form} />
            ))}
          </div>
        </>
      )}

      {data && tab === "things" && (
        <div className="things">
          {data.map((thing) => (
            <ThingTile key={thing.id} thing={thing} />
          ))}
        </div>
      )}
    </Modal>
  );
}

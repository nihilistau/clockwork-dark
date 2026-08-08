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
 *
 * WHAT CHANGED
 * ------------
 * The Atlas rendered as nine identical black rectangles. Nineteen of twenty
 * cards printed the word "Unwalked", the same fifteen-word sentence and an
 * empty picture box, over a diagonal hatch drawn between two surfaces about
 * two ΔE apart (invisible), under a vignette copied from the 320px hero whose
 * 70px blur and 14px spread covered the entire 169px tile, at 0.62 opacity.
 * Four separate things were erasing the same card.
 *
 * An undiscovered place now paints its ring's own light, says which ring it is
 * in, says how many roads reach it, and carries a line written for that place
 * and no other. It reads as somewhere you have not been, not as a rendering
 * failure.
 */
import React, { useEffect, useState } from "react";
import Modal from "@core/parts/Modal.jsx";
import { fetchPlaces, fetchSouls, fetchThings } from "@core/api.js";
import PaintFrame from "@core/parts/PaintFrame.jsx";
import { washFor, ringOf, unknownLine, RING_NAMES } from "../parts/SceneVisual.jsx";

const TABS = [
  {
    id: "places",
    label: "Atlas",
    loader: fetchPlaces,
    pick: (d) => d.places || [],
    kicker: "The Atlas",
    title: "Places & buildings",
    lede: "A frontier village at the edge of an old forest, arranged in rings. Beauty in bread steam and moss; dread at the margin, where the wheat turns wrong.",
    reading: "Unfolding the map…",
  },
  {
    id: "souls",
    label: "Souls",
    loader: fetchSouls,
    pick: (d) => d,
    kicker: "The Souls",
    title: "Who is out there",
    lede: "Everyone you have stood close enough to remember, and the five shapes the Assistant is willing to wear in front of you.",
    reading: "Asking after names…",
  },
  {
    id: "things",
    label: "Things",
    loader: fetchThings,
    pick: (d) => d.things || [],
    kicker: "The Things",
    title: "Goods & gear",
    lede: "Priced in copper, because this world never floats gold coins in the air. What you carry is marked.",
    reading: "Counting the stock…",
  },
];

// A stable small integer from an id, so a soul or an object gets its own
// palette instead of every portrait sharing one. Cheap FNV-ish walk; it only
// has to be deterministic, not good.
function hashOf(id) {
  let h = 0;
  for (let i = 0; i < String(id).length; i += 1) h = (h * 31 + String(id).charCodeAt(i)) >>> 0;
  return h;
}

const CHARS = ["wild", "hearth", "trade", "stone", "ruin", "under", "water", "sacred"];

/**
 * Deterministic wash for anything that is not a place on the ring map.
 *
 * `ring` is optional: left off, it is derived from the id too, which is what
 * keeps a column of unmet souls from being five amber blobs. Everything about
 * a given id is stable across reloads -- the same face is always the same
 * colour, which is the only way a placeholder can become recognisable.
 */
function moodWash(id, ring = null) {
  const h = hashOf(id);
  const char = CHARS[h % CHARS.length];
  const band = ring === null ? (h >> 5) % 4 : ring;
  const x = 32 + (h >> 3) % 40;
  const y = 12 + (h >> 7) % 46;
  return (
    `radial-gradient(56% 46% at ${x}% ${y}%, var(--char-${char}), transparent 66%), ` +
    `linear-gradient(${150 + ((h >> 11) % 46)}deg, var(--ring${band}-shade) 0%, ` +
    `var(--ring${band}-mid) 42%, var(--ring${band}-lift) 74%, var(--ring${band}-edge) 100%)`
  );
}

function SectionHead({ kicker, title, lede }) {
  return (
    <header className="sectionhead">
      <p className="sectionhead__kicker">{kicker}</p>
      <h3 className="sectionhead__title">{title}</h3>
      <p className="sectionhead__lede">{lede}</p>
      <span className="rule rule--woodcut" aria-hidden="true" />
    </header>
  );
}

/**
 * One painted plate.
 *
 * `size` is the vignette tuning, not decoration: see PaintFrame. A blank plate
 * is no longer a hatch — it is the place's own wash, which is the whole reason
 * twenty washes exist.
 */
function Plate({ src, alt, wash, size = "tile", caption, corrupted }) {
  return (
    <PaintFrame
      className="plate"
      size={size}
      wash={wash}
      caption={caption}
      corrupted={corrupted}
    >
      {src && <img className="paint__img is-loaded" src={src} alt={alt} loading="lazy" />}
    </PaintFrame>
  );
}

function PlaceCard({ place }) {
  const ring = ringOf(place.id);
  const roads = place.roads || [];
  const known = place.discovered;
  // The road table is what walking there earns you. The road COUNT is not a
  // secret — you can see how many tracks leave a place from a hilltop — and
  // it is the one number that separates a crossroads from a dead end on an
  // otherwise unknown card.
  const roadWord = roads.length === 1 ? "one road" : `${roads.length} roads`;

  return (
    <article className={`codexcard ${known ? "" : "is-unknown"}`} data-ring={ring}>
      <Plate
        src={place.image}
        alt={known ? place.name : ""}
        wash={washFor(place.id)}
        size="tile"
        caption={known ? undefined : "unwalked"}
      />
      <div className="codexcard__body">
        <div className="codexcard__head">
          <h4 className="codexcard__name">{place.name}</h4>
          {place.here && <span className="pill pill--brass">you are here</span>}
        </div>

        <p className="codexcard__role">
          {RING_NAMES[ring]} · ring {ring}
        </p>

        <p className="codexcard__note">
          {known
            ? `${roadWord} reach it.`
            : unknownLine(place.id)}
        </p>

        {known && roads.length > 0 ? (
          <ul className="roads">
            {roads.map((road) => (
              <li key={road.to} className="roads__item">
                <span>{road.name}</span>
                <span className="roads__cost">
                  {road.hours > 0 ? `${road.hours} h` : "adjacent"}
                  {road.danger_dc > 0 ? ` · DC ${road.danger_dc}` : ""}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="codexcard__hint">
            {roads.length > 0 ? `${roadWord} — unmeasured` : "no road you have heard of"}
          </p>
        )}
      </div>
    </article>
  );
}

function SoulCard({ soul }) {
  return (
    <article className={`codexcard ${soul.met ? "" : "is-unknown"}`}>
      <Plate
        src={soul.portrait}
        alt={soul.met ? soul.name : ""}
        wash={moodWash(soul.id)}
        size="portrait"
      />
      <div className="codexcard__body">
        {/* An unmet soul comes back from the server named "Someone", so a
            column of strangers was five cards with the same heading. Their
            ROLE is not gated -- the village will tell you there is a baker
            long before it tells you she is Maris -- so that is the heading
            until you have met them. */}
        <h4 className="codexcard__name">{soul.met ? soul.name : soul.role}</h4>
        <p className="codexcard__role">
          {soul.met ? soul.role : "unnamed"}
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
      <Plate
        src={form.portrait}
        alt={`The Assistant as ${form.form}`}
        wash={moodWash(`form-${form.form}`)}
        size="square"
      />
      <span className="formchip__label">{form.form}</span>
      {form.current && <span className="formchip__now">now</span>}
    </div>
  );
}

function ThingTile({ thing }) {
  return (
    <div className={`thing ${thing.carried > 0 ? "is-carried" : ""}`}>
      <Plate
        src={thing.image}
        alt={thing.name}
        wash={moodWash(thing.id)}
        size="square"
      />
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
  const entry = TABS.find((t) => t.id === tab);

  return (
    <Modal title="Codex" onClose={onClose} wide>
      {/* Toggle buttons rather than role="tab". The full tab pattern owes the
          reader arrow-key roving focus and an id-linked tabpanel; a half-built
          one announces affordances that are not there. */}
      <div className="codextabs" role="group" aria-label="Codex sections">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            aria-pressed={tab === t.id}
            className={`codextab ${tab === t.id ? "is-active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <SectionHead kicker={entry.kicker} title={entry.title} lede={entry.lede} />

      {error && <p className="overlay__error">{error}</p>}
      {!data && !error && (
        <p className="empty empty--waiting">
          <span className="empty__mark" aria-hidden="true" />
          {entry.reading}
        </p>
      )}

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
          {(data.souls || []).length === 0 ? (
            <p className="empty empty--souls">
              <span className="empty__mark" aria-hidden="true" />
              You have spoken to no one yet. The village is still a rumour.
            </p>
          ) : (
            <div className="codexgrid codexgrid--tight">
              {(data.souls || []).map((soul) => (
                <SoulCard key={soul.id} soul={soul} />
              ))}
            </div>
          )}
          <p className="overlay__kicker">The Assistant wears</p>
          <div className="formchips">
            {(data.forms || []).map((form) => (
              <FormChip key={form.form} form={form} />
            ))}
          </div>
        </>
      )}

      {data && tab === "things" && (
        data.length === 0 ? (
          <p className="empty empty--things">
            <span className="empty__mark" aria-hidden="true" />
            Nothing is for sale anywhere you have been.
          </p>
        ) : (
          <div className="things">
            {data.map((thing) => (
              <ThingTile key={thing.id} thing={thing} />
            ))}
          </div>
        )
      )}
    </Modal>
  );
}

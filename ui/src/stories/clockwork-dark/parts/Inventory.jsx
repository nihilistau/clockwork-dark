/**
 * The pack — a real inventory.
 *
 * WHAT THIS REPLACES: `<ul>` of `name ×qty` in Sheet.jsx. data/items/*.yaml
 * ships 74 items, each with prose, tags, a weight, a value and an art key, and
 * data/art/manifest.yaml maps a couple of dozen of them to real paintings in
 * static/art/things/. None of it reached the player, because the browser
 * cannot read YAML and no route handed it over — see GET /api/items.
 *
 * Crafting lives here too. `craft_item(recipe_id)` and `list_recipes()` have
 * been callable engine skills with no way for a player to discover a single
 * recipe id, so the "mundane craft as dignity" pillar was unreachable from the
 * UI entirely.
 *
 * NOTHING HERE MUTATES STATE. The pack presses INTENTS (v0.25.0 §7.3, §8.1):
 * Eat, Use, Wear/Ready, Take off and Make it each hand core an `{action,
 * target}` from `GET /api/intents/overlay`, which core emits as
 * `overlay_action`; the engine re-checks the pair under the turn lock and runs
 * its skill before the narrator speaks (rule 1). A pair the server does not
 * list is drawn and not pressable. Examine moves, spends and risks nothing, so
 * it stays the player's typed words. Offer and Drop are gone: no engine verb
 * gives or drops a thing (docs/GOVERNANCE.md, NOT WIRED).
 */
import React, { useEffect, useMemo, useState } from "react";
import Modal from "@core/parts/Modal.jsx";
import PaintFrame from "@core/parts/PaintFrame.jsx";
import { fetchItems, fetchRecipes } from "@core/api.js";
import { offerRow, overlayTurnKey, useOverlayIntents } from "@core/hooks/useOverlayIntents.js";
import ActionButton, { SceneOwnsTurn } from "./ActionButton.jsx";

const TAG_LABEL = {
  food: "Food",
  tool: "Tools",
  charm: "Charms",
  trade: "Trade",
  quest: "Quest",
  light: "Light",
  apparel: "Worn",
  material: "Materials",
  unregistered: "Unlisted",
};

/** A slot held in the hand reads "Ready"; any other slot is worn. */
const HELD_SLOTS = ["hands", "offhand"];

function Tile({ item, selected, onSelect }) {
  return (
    <button
      type="button"
      className={`packitem ${selected ? "is-selected" : ""} ${item.carried > 0 ? "is-carried" : ""}`}
      onClick={() => onSelect(item)}
      aria-pressed={selected}
    >
      <PaintFrame size="square" className="packitem__art">
        {item.image && (
          <img className="paint__img is-loaded" src={item.image} alt="" loading="lazy" />
        )}
        {item.carried > 1 && <span className="packitem__qty">×{item.carried}</span>}
      </PaintFrame>
      <span className="packitem__name">{item.name}</span>
    </button>
  );
}

/**
 * One thing in the pack, and what can be done with it.
 *
 * A verb's button is DRAWN from the server's list or, for Eat, from the item's
 * `food` tag too (ruling M20), so food the rules will not count is still shown
 * and says why it cannot be pressed. Tags only ever decide whether a button is
 * drawn; the server's list alone decides whether it can be pressed.
 */
function Detail({ item, offer, busy, onAct }) {
  if (!item) {
    return (
      <div className="packdetail packdetail--empty">
        <p className="overlay__empty">Pick something up.</p>
      </div>
    );
  }
  const held = item.carried > 0;
  return (
    <div className="packdetail">
      <PaintFrame size="tile" className="packdetail__plate" caption={item.name}>
        {item.image && <img className="paint__img is-loaded" src={item.image} alt={item.name} />}
      </PaintFrame>

      <h3 className="packdetail__name">{item.name}</h3>
      <div className="pills">
        {(item.tags || []).map((tag) => (
          <span key={tag} className="pill">
            {TAG_LABEL[tag] || tag}
          </span>
        ))}
        {held && <span className="pill pill--brass">carried ×{item.carried}</span>}
      </div>

      {item.description && <p className="packdetail__prose">{item.description}</p>}

      <dl className="packdetail__facts">
        <div>
          <dt>Weight</dt>
          <dd>{item.weight ? `${item.weight} kg` : "—"}</dd>
        </div>
        <div>
          <dt>Worth</dt>
          {/* Copper. The design brief is explicit that this world never floats
              gold coins in the air. */}
          <dd>{item.value ? `${item.value}c` : "—"}</dd>
        </div>
        <div>
          <dt>Traded by</dt>
          <dd>{item.vendor || "nobody here"}</dd>
        </div>
      </dl>

      {held ? (
        <div className="packactions">
          {(offerRow(offer, "eat", item.id) || item.tags?.includes("food")) && (
            <ActionButton offer={offer} action="eat" target={item.id} busy={busy} onAct={onAct} verb="Eat"
              why="Not something that will fill you.">
              Eat
            </ActionButton>
          )}
          {offerRow(offer, "use", item.id) && (
            <ActionButton offer={offer} action="use" target={item.id} busy={busy} onAct={onAct} verb="Use">
              Use
            </ActionButton>
          )}
          {offerRow(offer, "equip", item.id) && (
            <ActionButton offer={offer} action="equip" target={item.id} busy={busy} onAct={onAct}
              verb={HELD_SLOTS.includes(offerRow(offer, "equip", item.id).slot) ? "Ready" : "Wear"}>
              {HELD_SLOTS.includes(offerRow(offer, "equip", item.id).slot) ? "Ready" : "Wear"}
            </ActionButton>
          )}
          {offerRow(offer, "unequip", item.id) && (
            <ActionButton offer={offer} action="unequip" target={item.id} busy={busy} onAct={onAct} verb="Take off">
              Take off
            </ActionButton>
          )}
          <button
            type="button"
            className="btn btn--sm"
            aria-disabled={busy ? "true" : undefined}
            onClick={() => !busy && onAct(`You look closely at the ${item.name.toLowerCase()}.`)}
          >
            Examine
          </button>
        </div>
      ) : (
        <p className="packdetail__note">
          You are not carrying this. {item.vendor ? `${sentenceCase(item.vendor)} deals in it.` : ""}
        </p>
      )}
    </div>
  );
}

function Recipe({ recipe, offer, busy, onAct }) {
  // Exactly the gates craft_item enforces, said in the order it checks them,
  // so a button that cannot be pressed always explains itself.
  const why = recipe.makeable
    ? "You could do this now."
    : !recipe.here
      ? `That work happens at ${String(recipe.station).replace(/_/g, " ")}.`
      : !recipe.has_tools
        ? "You do not have the tools."
        : "You are short of materials.";
  return (
    <article className={`recipe ${recipe.makeable ? "is-makeable" : ""}`}>
      <div className="recipe__head">
        <h3 className="recipe__name">{recipe.name}</h3>
        <span className="recipe__cost">
          {recipe.hours} h · {recipe.skill} ({recipe.band})
        </span>
      </div>

      <div className="recipe__flow">
        <ul className="ingredients">
          {recipe.inputs.map((i) => (
            <li key={i.id} className={`ingredient ${i.have >= i.qty ? "is-held" : "is-short"}`}>
              <PaintFrame size="square" className="ingredient__art">
                {i.image && <img className="paint__img is-loaded" src={i.image} alt="" loading="lazy" />}
              </PaintFrame>
              <span className="ingredient__name">{i.name}</span>
              <span className="ingredient__count">
                {i.have}/{i.qty}
              </span>
            </li>
          ))}
          {recipe.inputs.length === 0 && <li className="ingredient is-held">nothing but time</li>}
        </ul>
        <span className="recipe__arrow" aria-hidden="true">
          →
        </span>
        <div className="recipe__out">
          <PaintFrame size="square" className="ingredient__art">
            {recipe.output.image && (
              <img className="paint__img is-loaded" src={recipe.output.image} alt="" loading="lazy" />
            )}
          </PaintFrame>
          <span className="ingredient__name">
            {recipe.output.name}
            {recipe.output.qty > 1 ? ` ×${recipe.output.qty}` : ""}
          </span>
        </div>
      </div>

      {recipe.tools.length > 0 && (
        <p className="recipe__tools">
          Needs in hand:{" "}
          {recipe.tools.map((t) => (
            <span key={t.id} className={t.have > 0 ? "is-held" : "is-short"}>
              {t.name}
            </span>
          ))}
        </p>
      )}

      <div className="recipe__foot">
        <span className="recipe__why">{why}</span>
        <ActionButton offer={offer} action="craft" target={recipe.id} busy={busy} onAct={onAct} why={why} verb="Make">
          Make it
        </ActionButton>
      </div>
    </article>
  );
}

/** "the baker" opening a sentence reads "The baker" (T3 re-review R4). */
export function sentenceCase(text) {
  const words = String(text || "");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export default function Inventory({ state, sessionId, busy, onAct, onClose }) {
  const [tab, setTab] = useState("carried");
  const [tag, setTag] = useState("");
  const [pack, setPack] = useState(null);
  const [book, setBook] = useState(null);
  const [selectedId, setSelectedId] = useState("");
  const [error, setError] = useState("");
  const { offer } = useOverlayIntents(sessionId, overlayTurnKey(state));

  useEffect(() => {
    let live = true;
    Promise.all([fetchItems(sessionId), fetchRecipes(sessionId)])
      .then(([items, recipes]) => {
        if (!live) return;
        setPack(items);
        setBook(recipes);
      })
      .catch(() => live && setError("The pack will not open."));
    return () => {
      live = false;
    };
  }, [sessionId]);

  const items = pack?.items || [];
  const visible = useMemo(() => {
    let rows = tab === "carried" ? items.filter((i) => i.carried > 0) : items;
    if (tag) rows = rows.filter((i) => (i.tags || []).includes(tag));
    return rows;
  }, [items, tab, tag]);

  // Follow the filter rather than stranding a selection the list no longer
  // shows: a detail pane describing an invisible item reads as a bug.
  const selected = visible.find((i) => i.id === selectedId) || visible[0] || null;

  const tags = useMemo(() => {
    const source = tab === "carried" ? items.filter((i) => i.carried > 0) : items;
    return [...new Set(source.flatMap((i) => i.tags || []))].sort();
  }, [items, tab]);

  // A string (Examine) or an `{action, target, label}` intent: core routes both.
  function act(what) {
    onAct(what);
    onClose();
  }

  return (
    <Modal title="The pack" onClose={onClose} wide>
      <SceneOwnsTurn offer={offer} />
      <div className="pack__head">
        <span className="pack__stat">
          <b>{pack ? pack.carried_count : "—"}</b> carried
        </span>
        <span className="pack__stat">
          <b>{pack ? pack.carried_weight : "—"}</b> kg
        </span>
        <span className="pack__stat">
          <b>{pack ? pack.gold : "—"}</b> coin
        </span>
      </div>

      <div className="packtabs" role="group" aria-label="Pack sections">
        {[
          { id: "carried", label: "Carried" },
          { id: "all", label: "Everything" },
          { id: "craft", label: "Making" },
        ].map((entry) => (
          <button
            key={entry.id}
            type="button"
            className={`packtab ${tab === entry.id ? "is-active" : ""}`}
            aria-pressed={tab === entry.id}
            onClick={() => {
              setTab(entry.id);
              setTag("");
            }}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {error && <p className="overlay__error">{error}</p>}
      {!pack && !error && <p className="overlay__empty">Rummaging…</p>}

      {pack && tab !== "craft" && (
        <>
          {tags.length > 1 && (
            <div className="pack__filters" role="group" aria-label="Filter by kind">
              <button
                type="button"
                className={`tagchip ${tag === "" ? "is-active" : ""}`}
                onClick={() => setTag("")}
              >
                All
              </button>
              {tags.map((t) => (
                <button
                  key={t}
                  type="button"
                  className={`tagchip ${tag === t ? "is-active" : ""}`}
                  onClick={() => setTag(t)}
                >
                  {TAG_LABEL[t] || t}
                </button>
              ))}
            </div>
          )}

          <div className="pack__body">
            <div className="packgrid">
              {visible.map((item) => (
                <Tile
                  key={item.id}
                  item={item}
                  selected={selected?.id === item.id}
                  onSelect={(i) => setSelectedId(i.id)}
                />
              ))}
              {visible.length === 0 && (
                <p className="overlay__empty">Nothing but what you stand in.</p>
              )}
            </div>
            <Detail item={selected} offer={offer} busy={busy} onAct={act} />
          </div>
        </>
      )}

      {book && tab === "craft" && (
        <div className="recipes">
          {book.recipes.map((recipe) => (
            <Recipe key={recipe.id} recipe={recipe} offer={offer} busy={busy} onAct={act} />
          ))}
          {book.recipes.length === 0 && (
            <p className="overlay__empty">Nothing anyone has written down.</p>
          )}
        </div>
      )}
    </Modal>
  );
}

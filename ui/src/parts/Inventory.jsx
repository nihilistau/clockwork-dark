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
 * NOTHING HERE MUTATES STATE. Every action composes a sentence and sends it as
 * an ordinary turn (`player_choice` with custom_text), so the engine stays the
 * only writer of inventory, gold and the clock. A button that quietly POSTed
 * an item away would be a second, unaudited writer.
 */
import React, { useEffect, useMemo, useState } from "react";
import Modal from "./Modal.jsx";
import { PaintFrame } from "./SceneVisual.jsx";
import { fetchItems, fetchRecipes } from "../api.js";

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

/**
 * The verbs an item earns, from its tags.
 *
 * Tag-driven rather than a per-item table: the registry's tag vocabulary is
 * fixed (see the field reference in data/items/food.yaml) and a new item then
 * gets the right verbs for free.
 */
function actionsFor(item) {
  const tags = item.tags || [];
  const name = item.name.toLowerCase();
  const out = [];
  if (tags.includes("food")) out.push({ id: "eat", label: "Eat", text: `You eat the ${name}.` });
  if (tags.includes("light"))
    out.push({ id: "light", label: "Light", text: `You light the ${name}.` });
  if (tags.includes("charm") || tags.includes("apparel"))
    out.push({ id: "wear", label: "Wear", text: `You put on the ${name}.` });
  if (tags.includes("tool"))
    out.push({ id: "equip", label: "Ready", text: `You take the ${name} in hand.` });
  out.push({ id: "look", label: "Examine", text: `You look closely at the ${name}.` });
  out.push({
    id: "give",
    label: "Offer",
    text: `You offer the ${name} to whoever is nearest.`,
  });
  out.push({ id: "drop", label: "Drop", text: `You put the ${name} down and leave it.` });
  return out;
}

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

function Detail({ item, busy, onAct }) {
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
          {actionsFor(item).map((action) => (
            <button
              key={action.id}
              type="button"
              className="btn btn--sm"
              disabled={busy}
              onClick={() => onAct(action.text)}
            >
              {action.label}
            </button>
          ))}
        </div>
      ) : (
        <p className="packdetail__note">
          You are not carrying this. {item.vendor ? `${item.vendor} deals in it.` : ""}
        </p>
      )}
    </div>
  );
}

function Recipe({ recipe, busy, onAct }) {
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
        {/* Exactly the gates craft_item enforces, said in the order it checks
            them, so a disabled button always explains itself. */}
        <span className="recipe__why">
          {recipe.makeable
            ? "You could do this now."
            : !recipe.here
              ? `That work happens at ${String(recipe.station).replace(/_/g, " ")}.`
              : !recipe.has_tools
                ? "You do not have the tools."
                : "You are short of materials."}
        </span>
        <button
          type="button"
          className="btn btn--sm"
          disabled={busy || !recipe.makeable}
          // The recipe id rides along in plain sight so the Storyteller can
          // pass it straight to craft_item(recipe_id) rather than guessing.
          onClick={() => onAct(`Set to work: ${recipe.name} (recipe ${recipe.id}).`)}
        >
          Make it
        </button>
      </div>
    </article>
  );
}

export default function Inventory({ sessionId, busy, onAct, onClose }) {
  const [tab, setTab] = useState("carried");
  const [tag, setTag] = useState("");
  const [pack, setPack] = useState(null);
  const [book, setBook] = useState(null);
  const [selectedId, setSelectedId] = useState("");
  const [error, setError] = useState("");

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

  function act(text) {
    onAct(text);
    onClose();
  }

  return (
    <Modal title="The pack" onClose={onClose} wide>
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
            <Detail item={selected} busy={busy} onAct={act} />
          </div>
        </>
      )}

      {book && tab === "craft" && (
        <div className="recipes">
          {book.recipes.map((recipe) => (
            <Recipe key={recipe.id} recipe={recipe} busy={busy} onAct={act} />
          ))}
          {book.recipes.length === 0 && (
            <p className="overlay__empty">Nothing anyone has written down.</p>
          )}
        </div>
      )}
    </Modal>
  );
}

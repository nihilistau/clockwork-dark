// @vitest-environment jsdom
/**
 * The flagship's overlays press intents (v0.25.0 §7.3, §8.1): each button is an `{action, target}` the
 * server lists (`/api/intents/overlay`); a pair not listed is drawn and not pressable; while a scene owns
 * the turn nothing is pressable; Examine stays typed text; Offer and Drop are gone.
 *
 * The fixtures use the routes' own keys (`engine/scenes/default_api.py`): `/api/trade`'s
 * `vendors[].npc_id` and `sells[].id`, `/api/notices`' `notices` and `elsewhere`.
 */
import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { button, click, mount } from "./helpers/dom.js";
import Inventory from "../src/stories/clockwork-dark/parts/Inventory.jsx";
import Notices from "../src/stories/clockwork-dark/screens/Notices.jsx";
import Trade from "../src/stories/clockwork-dark/screens/Trade.jsx";

const ITEMS = {
  items: [
    { id: "loaf", name: "Loaf", tags: ["food"], carried: 2, description: "", weight: 0.5, value: 2 },
    // Food the server does NOT list under `eat` (ruling I4): drawn, never pressable.
    { id: "apple", name: "Apple", tags: ["food"], carried: 1, description: "", weight: 0.2, value: 1 },
    { id: "wool_cloak", name: "Wool cloak", tags: ["apparel"], carried: 1, description: "", weight: 2, value: 8 },
    { id: "poultice", name: "Poultice", tags: ["tool"], carried: 1, description: "", weight: 0.1, value: 3 },
  ],
  carried_count: 5,
  carried_weight: 3.3,
  gold: 4,
};
const RECIPES = {
  recipes: [
    {
      id: "bread", name: "Bread", category: "food", skill: "craft", band: "easy", hours: 2, station: "",
      here: true, makeable: false, has_inputs: false, has_tools: true,
      inputs: [{ id: "flour", name: "Flour", qty: 1, have: 0, image: "" }], tools: [],
      output: { id: "loaf", name: "Loaf", qty: 1, image: "" },
    },
  ],
};
const OFFER = {
  scene_owns_turn: false,
  actions: {
    eat: [{ target: "loaf", label: "Loaf" }],
    equip: [{ target: "wool_cloak", label: "Wool cloak", slot: "back" }],
    unequip: [], use: [], buy: [{ target: "npc_maris/loaf", label: "Loaf from Maris, 2c" }],
    sell: [], craft: [], work: [{ target: "bakery_morning", label: "Morning at the ovens" }],
  },
};
const TRADE = { gold: 4, vendors: [{ npc_id: "npc_maris", name: "Maris", known: true, role: "baker", sells: [
  { id: "loaf", name: "Loaf", price: 2, image: "" },
  { id: "flour", name: "Flour", price: 9, image: "" }], buys: [] }] };
const NOTICES = { location_name: "Edgewood Square",
                  notices: [{ id: "bakery_morning", name: "Morning at the ovens", expected_wage: 3, hours: 4 }],
                  elsewhere: [{ id: "gate_watch", name: "Gate watch", location_id: "millhaven_gate", hiring: true }] };

function serve(offer = OFFER) {
  globalThis.fetch = vi.fn(async (url) => {
    const path = String(url).split("?")[0];
    const body = { "/api/intents/overlay": offer, "/api/items": ITEMS, "/api/recipes": RECIPES,
                   "/api/trade": TRADE, "/api/notices": NOTICES, "/api/codex/places": { places: [{ id: "millhaven_gate", name: "Millhaven Gate" }] } }[path] || {};
    return { ok: true, status: 200, json: async () => body };
  });
}

let view;
beforeEach(() => {
  view = mount();
});
afterEach(() => view.unmount());

const props = (onAct) => ({ sessionId: "s1", busy: false, onAct, onClose: () => {}, state: { world: { turn_number: 3 } } });

// A pack tile's text is its count and its name ("×2Loaf"), so a tile is found by the name it ends with.
const tile = (name) => button(view.host, new RegExp(`${name}$`));

describe("the pack", () => {
  it("presses Eat as an intent", async () => {
    serve();
    const onAct = vi.fn();
    await view.renderAsync(<Inventory {...props(onAct)} />);
    await view.renderAsync(<Inventory {...props(onAct)} />);
    click(tile("Loaf"));
    click(button(view.host, "Eat"));
    expect(onAct).toHaveBeenCalledWith({ action: "eat", target: "loaf", label: "Eat: Loaf" });
  });
  it("says Wear for a worn slot, from the list, not from tags", async () => {
    serve();
    const onAct = vi.fn();
    await view.renderAsync(<Inventory {...props(onAct)} />);
    await view.renderAsync(<Inventory {...props(onAct)} />);
    click(tile("Wool cloak"));
    click(button(view.host, "Wear"));
    expect(onAct).toHaveBeenCalledWith({ action: "equip", target: "wool_cloak", label: "Wear: Wool cloak" });
  });
  it("logs the verb with the thing: Take off is not Wear (T14)", async () => {
    serve({ ...OFFER, actions: { ...OFFER.actions, equip: [], unequip: [{ target: "wool_cloak", label: "Wool cloak" }] } });
    const onAct = vi.fn();
    await view.renderAsync(<Inventory {...props(onAct)} />);
    await view.renderAsync(<Inventory {...props(onAct)} />);
    click(tile("Wool cloak"));
    click(button(view.host, "Take off"));
    expect(onAct).toHaveBeenCalledWith({ action: "unequip", target: "wool_cloak", label: "Take off: Wool cloak" });
  });
  it("draws food the server does not list and does not press it", async () => {
    serve();
    const onAct = vi.fn();
    await view.renderAsync(<Inventory {...props(onAct)} />);
    await view.renderAsync(<Inventory {...props(onAct)} />);
    click(tile("Apple"));
    const eat = button(view.host, "Eat");
    expect(eat).not.toBeNull();
    expect(eat.getAttribute("aria-disabled")).toBe("true");
    click(eat);
    expect(onAct).not.toHaveBeenCalled();
  });
  it("draws no verb a tag alone would have promised (a tool is not Readied by its tag)", async () => {
    serve();
    const onAct = vi.fn();
    await view.renderAsync(<Inventory {...props(onAct)} />);
    await view.renderAsync(<Inventory {...props(onAct)} />);
    click(tile("Poultice"));
    expect(button(view.host, "Ready")).toBeNull();
    expect(button(view.host, "Use")).toBeNull();
    expect(button(view.host, "Examine")).not.toBeNull();
  });
  it("draws a recipe the server does not list and does not press it", async () => {
    serve();
    const onAct = vi.fn();
    await view.renderAsync(<Inventory {...props(onAct)} />);
    await view.renderAsync(<Inventory {...props(onAct)} />);
    click(button(view.host, "Making"));
    const make = button(view.host, "Make it");
    expect(make.getAttribute("aria-disabled")).toBe("true");
    click(make);
    expect(onAct).not.toHaveBeenCalled();
  });
  it("presses a listed recipe as a craft intent", async () => {
    serve({ ...OFFER, actions: { ...OFFER.actions, craft: [{ target: "bread", label: "Bread" }] } });
    const onAct = vi.fn();
    await view.renderAsync(<Inventory {...props(onAct)} />);
    await view.renderAsync(<Inventory {...props(onAct)} />);
    click(button(view.host, "Making"));
    click(button(view.host, "Make it"));
    expect(onAct).toHaveBeenCalledWith({ action: "craft", target: "bread", label: "Make: Bread" });
  });
  it("keeps Examine as typed text and has no Offer or Drop", async () => {
    serve();
    const onAct = vi.fn();
    await view.renderAsync(<Inventory {...props(onAct)} />);
    await view.renderAsync(<Inventory {...props(onAct)} />);
    click(tile("Loaf"));
    click(button(view.host, "Examine"));
    expect(typeof onAct.mock.calls[0][0]).toBe("string");
    expect(button(view.host, "Offer")).toBeNull();
    expect(button(view.host, "Drop")).toBeNull();
  });
  it("presses nothing while a scene owns the turn, and says so", async () => {
    serve({ ...OFFER, scene_owns_turn: true });
    const onAct = vi.fn();
    await view.renderAsync(<Inventory {...props(onAct)} />);
    await view.renderAsync(<Inventory {...props(onAct)} />);
    click(tile("Loaf"));
    click(button(view.host, "Eat"));
    expect(onAct).not.toHaveBeenCalled();
    expect(view.host.textContent).toContain("Answer what is in front of you first");
  });
  it("presses nothing while a turn runs", async () => {
    serve();
    const onAct = vi.fn();
    await view.renderAsync(<Inventory {...props(onAct)} busy />);
    await view.renderAsync(<Inventory {...props(onAct)} busy />);
    click(tile("Loaf"));
    click(button(view.host, "Eat"));
    expect(onAct).not.toHaveBeenCalled();
  });
});

describe("barter and the board", () => {
  it("buys one row with one press, and the unaffordable row is drawn and not pressable", async () => {
    serve();
    const onAct = vi.fn();
    await view.renderAsync(<Trade {...props(onAct)} />);
    await view.renderAsync(<Trade {...props(onAct)} />);
    click(button(view.host, /Buy · 2c/));
    expect(onAct).toHaveBeenCalledWith({ action: "buy", target: "npc_maris/loaf", label: "Buy: Loaf from Maris, 2c" });
    expect(button(view.host, /Buy · 9c/).getAttribute("aria-disabled")).toBe("true");
    expect(button(view.host, "Strike the bargain")).toBeNull();
  });
  it("takes a shift posted here, and shows where the rest are", async () => {
    serve();
    const onAct = vi.fn();
    await view.renderAsync(<Notices {...props(onAct)} />);
    await view.renderAsync(<Notices {...props(onAct)} />);
    click(button(view.host, "Take the shift"));
    expect(onAct).toHaveBeenCalledWith({ action: "work", target: "bakery_morning", label: "Work: Morning at the ovens" });
    expect(view.host.textContent).toContain("Gate watch");
    expect(view.host.textContent).toContain("at Millhaven Gate");
    expect(view.host.querySelectorAll("button").length).toBe(2); // the close button and the one shift
  });
  it("refetches its list when a turn arrives and after a stale refusal", async () => {
    serve();
    const onAct = vi.fn();
    await view.renderAsync(<Notices {...props(onAct)} />);
    const before = globalThis.fetch.mock.calls.filter(([u]) => String(u).startsWith("/api/intents/overlay")).length;
    await view.renderAsync(<Notices {...props(onAct)} state={{ world: { turn_number: 4 } }} />);
    await view.renderAsync(<Notices {...props(onAct)} state={{ world: { turn_number: 4 }, error: "That is not on offer here and now." }} />);
    const after = globalThis.fetch.mock.calls.filter(([u]) => String(u).startsWith("/api/intents/overlay")).length;
    expect(after).toBe(before + 2);
  });
});

describe("an unpressable button (T14)", () => {
  it("neither glows nor sinks: its hover and press rows outrank core's", () => {
    const css = readFileSync(resolve(process.cwd(), "src/stories/clockwork-dark/theme/clockwork-dark.css"), "utf8");
    // Core's `.btn:hover:not(:disabled)` and `.btn:active:not(:disabled)` are 0,3,0 and match an
    // aria-disabled button; the flagship's rows add the attribute (0,4,0).
    const rule = css.slice(css.indexOf('.btn[aria-disabled="true"],'));
    const head = rule.slice(0, rule.indexOf("{"));
    expect(head).toContain('.btn[aria-disabled="true"]:hover:not(:disabled)');
    expect(head).toContain('.btn[aria-disabled="true"]:active:not(:disabled)');
    const body = rule.slice(rule.indexOf("{"), rule.indexOf("}"));
    for (const decl of ["box-shadow: none", "filter: none", "transform: none"]) expect(body).toContain(decl);
  });
});

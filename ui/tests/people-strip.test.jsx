// @vitest-environment jsdom
import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PeopleStrip from "../src/core/panels/PeopleStrip.jsx";

const WORLD = { location_id: "tallow_docks", world_hour: 9, turn_number: 3 };
const MET = { key: "p0", known: true, name: "Sergeant Brask", role_label: "watch sergeant", activity: "eating a pastry on a bollard", portrait: "/story-art/portraits/brask.jpg" };
const STRANGER = { key: "p1", known: false, name: "", role_label: "dock boss", activity: "shouting at a gang of porters", portrait: "" };

let host;
let root;
let fetches;
let answer;

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  fetches = [];
  answer = { people: [MET, STRANGER], more: 3 };
  globalThis.fetch = vi.fn(async (url) => {
    fetches.push(String(url));
    return { ok: true, status: 200, json: async () => answer };
  });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  React.act(() => root.unmount());
  host.remove();
});

async function draw(world = WORLD, sessionId = "s1") {
  await React.act(async () => root.render(<PeopleStrip state={{ sessionId, world }} region="stage" />));
}

describe("the people strip", () => {
  it("renders nothing for an empty place", async () => {
    answer = { people: [], more: 0 };
    await draw();
    expect(host.innerHTML).toBe("");
  });

  it("shows a met person's portrait with their name as alt, and a stranger as a monogram and a role", async () => {
    await draw();
    const img = host.querySelector("img");
    expect(img.getAttribute("alt")).toBe("Sergeant Brask");
    const cards = [...host.querySelectorAll(".people__card")];
    expect(cards[1].querySelector("img")).toBeNull();
    expect(cards[1].querySelector(".people__monogram").getAttribute("aria-hidden")).toBe("true");
    expect(cards[1].textContent).toContain("dock boss");
    expect(host.textContent).toContain("+3 more");
  });

  it("is a list under a visually hidden 'Here' heading", async () => {
    await draw();
    expect(host.querySelector("h2").textContent).toBe("Here");
    expect(host.querySelectorAll("ul > li.people__card")).toHaveLength(2);
  });

  it("refetches when the hour, the place or the turn moves -- not on every render", async () => {
    await draw();
    await draw();
    expect(fetches).toHaveLength(1);
    expect(fetches[0]).toBe("/api/people?session_id=s1");
    await draw({ ...WORLD, world_hour: 10 });
    expect(fetches).toHaveLength(2);
  });

  it("shows a met person with no portrait as their initial, and a stranger by nothing but role and activity", async () => {
    answer = { people: [{ ...MET, portrait: "" }, STRANGER], more: 0 };
    await draw();
    const [met, stranger] = [...host.querySelectorAll(".people__card")];
    expect(met.querySelector(".people__monogram").textContent).toBe("S");
    expect(met.textContent).toContain("Sergeant Brask");
    expect(stranger.querySelector(".people__monogram svg")).not.toBeNull();
    expect(stranger.querySelector(".people__who").textContent).toBe("dock boss");
    expect(host.textContent).not.toContain("+");
  });

  it("is a column in the ledger", async () => {
    await React.act(async () => root.render(<PeopleStrip state={{ sessionId: "s1", world: WORLD }} region="ledger" />));
    expect(host.querySelector("section").className).toContain("people--ledger");
  });

  it("fetches nothing without a session", async () => {
    await draw(WORLD, "");
    expect(fetches).toHaveLength(0);
    expect(host.innerHTML).toBe("");
  });

  it("is the registry's `people` component", async () => {
    const { PANELS } = await import("../src/core/panels/registry.js");
    expect(PANELS.find((panel) => panel.id === "people").Component).toBe(PeopleStrip);
  });

  it("never shows a stranger's name or portrait, even if a row carried them", async () => {
    answer = {
      people: [{ key: "p1", known: false, name: "Mother Gannet", role_label: "fence", activity: "counting", portrait: "/story-art/portraits/npc_gannet.jpg" }],
      more: 0,
    };
    await draw();
    expect(host.querySelector("img")).toBeNull();
    expect(host.innerHTML).not.toContain("Mother Gannet");
    expect(host.innerHTML).not.toContain("npc_gannet");
    expect(host.innerHTML).not.toContain(">M<");
    expect(host.querySelector(".people__who").textContent).toBe("fence");
  });

  it("renders nothing for a session the server does not own (404)", async () => {
    globalThis.fetch = vi.fn(async () => ({ ok: false, status: 404, json: async () => ({ error: "session not found" }) }));
    await draw();
    expect(host.innerHTML).toBe("");
  });

  it("never shows the last run's people under a new session", async () => {
    await draw();
    expect(host.textContent).toContain("Sergeant Brask");
    let release;
    globalThis.fetch = vi.fn(() => new Promise((resolve) => {
      release = () => resolve({ ok: true, status: 200, json: async () => ({ people: [STRANGER], more: 0 }) });
    }));
    await draw(WORLD, "s2");
    expect(host.textContent).not.toContain("Sergeant Brask");
    await React.act(async () => release());
    expect(host.textContent).toContain("dock boss");
  });

  it("renders nothing when the fetch fails", async () => {
    globalThis.fetch = vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) }));
    await draw();
    expect(host.innerHTML).toBe("");
  });
});

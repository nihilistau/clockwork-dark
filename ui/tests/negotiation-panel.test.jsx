// @vitest-environment jsdom
/**
 * The author's view of a negotiated turn.
 *
 * `negotiation` has ridden the turn payload since the multi-agent pipeline
 * shipped, with no reader anywhere in `ui/src/` -- `docs/GOVERNANCE.md` carried
 * it as a NOT WIRED row reading "the player currently has no way to know a
 * second agent won, lost or gave something up".
 *
 * What this file holds is the half that is NOT the player's: a collapsed,
 * debug-shaped panel for tuning the rule table. The player's half is the prose
 * (the narrator is handed the concession now -- see
 * `engine/agents/pipeline.py::narration_block`) plus a margin mark on the log
 * entry, and neither of those is a table.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import NegotiationPanel from "../src/core/parts/NegotiationPanel.jsx";

const contested = {
  ran: true,
  lead: "sophia",
  beats: ["she answers", "the court arrives"],
  resolutions: [
    {
      rule: "private_scene_finishes",
      winner: "sophia",
      loser: "gm",
      detail: "her scene completes; the world's event becomes its aftermath",
    },
  ],
};

let host;
let root;

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  React.act(() => root.unmount());
  host.remove();
});

function draw(negotiation) {
  React.act(() => root.render(<NegotiationPanel negotiation={negotiation} />));
}

function open() {
  React.act(() => host.querySelector("button").click());
}

describe("the negotiation panel", () => {
  it("renders nothing for a story that runs no pipeline", () => {
    // The flagship declares one participant, so `ran` is false and no key is
    // sent at all. It must cost that story nothing on screen.
    draw(null);
    expect(host.innerHTML).toBe("");

    draw({ ran: false });
    expect(host.innerHTML).toBe("");
  });

  it("summarises who led and how many gave way, collapsed", () => {
    draw(contested);
    expect(host.textContent).toMatch(/sophia led; 1 gave way/i);
    // Collapsed by default: a tuning surface, not something to read every turn.
    expect(host.textContent).not.toMatch(/her scene completes/);
  });

  it("opens onto the reason the author wrote for the rule", () => {
    draw(contested);
    open();

    expect(host.textContent).toMatch(/her scene completes/);
    expect(host.textContent).toMatch(/gm → sophia/);
    expect(host.textContent).toMatch(/she answers/);
  });

  it("says so plainly when nobody was contested", () => {
    draw({
      ran: true,
      lead: "gm",
      resolutions: [{ rule: "confidence", winner: "gm", detail: "highest confidence leads" }],
    });
    expect(host.textContent).toMatch(/gm led, uncontested/i);
  });

  it("never prints a private motive, because the payload never carries one", () => {
    // Belt and braces against the one leak that would make the knowledge
    // partition decorative. The pipeline drops `private` before building this
    // dict; if it ever appears here, the bug is upstream.
    draw({ ...contested, private: "I intend to keep them" });
    open();
    expect(host.textContent).not.toMatch(/I intend to keep them/);
  });
});

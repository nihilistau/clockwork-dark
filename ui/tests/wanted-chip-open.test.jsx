// @vitest-environment jsdom
/**
 * The wanted chip opens its poster (v0.21.0 T8 fix round 1, spec §4.1): a
 * collapsed poster is opened, the Sheet tab is chosen on a phone only when the
 * poster lives in the ledger, and the heading takes focus.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/core/parts/MicButton.jsx", () => ({ default: () => null }));

import Panel from "../src/core/panels/Panel.jsx";
import Play from "../src/core/screens/Play.jsx";
import { initialState } from "../src/core/store.js";

const LAW = {
  guise_label: "your own face",
  wanted: { "the Quay": "wanted" },
  clarity: "a likeness",
  custody: null,
  scales: { wanted: ["unknown", "noticed", "sought", "wanted", "hunted"], clarity: ["nothing", "a rumour", "a description", "a likeness"] },
};

const state = {
  ...initialState,
  screen: "scene",
  sessionId: "s1",
  link: "live",
  world: { location_id: "x", location_name: "Docks", world_day: 1, time_of_day: "day", law: LAW },
  log: [{ id: "e1", kind: "narration", text: "Loud." }],
  choices: [{ id: "a", text: "Wait" }],
};

let host;
let root;
const realMatchMedia = window.matchMedia;

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  React.act(() => root.unmount());
  host.remove();
  window.matchMedia = realMatchMedia;
});

const narrowPhone = () => {
  window.matchMedia = (q) => ({ matches: q.includes("max-width"), addEventListener() {}, removeEventListener() {} });
};

function draw(story) {
  const noop = () => {};
  React.act(() =>
    root.render(
      <Play state={state} story={{ slug: "probe", title: "Probe", overlays: [], onboarding: [], ...story }}
        onChoose={noop} onCustom={noop} onRetry={noop} onOpenSaves={noop} onOpenSettings={noop}
        onOpenOverlay={noop} onOpenMenu={noop} onToggleReasoning={noop} composeRef={{ current: null }} />
    )
  );
}

describe("a collapsible panel", () => {
  it("opens when its id is sent, and ignores another's", () => {
    React.act(() => root.render(<Panel id="p" title="P" collapsible defaultOpen={false}><i /></Panel>));
    const toggle = () => host.querySelector(".panel__toggle").getAttribute("aria-expanded");
    expect(toggle()).toBe("false");
    React.act(() => window.dispatchEvent(new CustomEvent("panel:open", { detail: "other" })));
    expect(toggle()).toBe("false");
    React.act(() => window.dispatchEvent(new CustomEvent("panel:open", { detail: "p" })));
    expect(toggle()).toBe("true");
  });
});

describe("the chip's press", () => {
  it("opens a collapsed poster", () => {
    draw({});
    const toggle = host.querySelector(".panel--wanted .panel__toggle");
    React.act(() => toggle.click());
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    React.act(() => host.querySelector(".wanted-chip").click());
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
  });

  it("switches a phone to the Sheet tab when the poster is in the ledger", () => {
    narrowPhone();
    draw({});
    expect(host.querySelector(".scene").getAttribute("data-tab")).toBe("scene");
    React.act(() => host.querySelector(".wanted-chip").click());
    expect(host.querySelector(".scene").getAttribute("data-tab")).toBe("sheet");
  });

  it("stays on the Scene tab when the poster was put on the shelf", () => {
    narrowPhone();
    draw({ panelDeclaration: [{ id: "wanted", region: "shelf" }] });
    React.act(() => host.querySelector(".wanted-chip").click());
    expect(host.querySelector(".scene").getAttribute("data-tab")).toBe("scene");
  });
});

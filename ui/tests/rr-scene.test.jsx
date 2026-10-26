// @vitest-environment jsdom
// ui/tests/rr-scene.test.jsx -- the companion card and scene choices (v0.23.0 T23, spec §14.1, §19.9).
import React from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import Companion from "../src/stories/read-receipts/world/Companion.jsx";
import World from "../src/stories/read-receipts/world/World.jsx";
import { phoneFixture } from "./fixtures/phone.js";
import { worldState } from "./fixtures/phone-harness.jsx";
import { byTestId, mount } from "./helpers/dom.js";

let view;
beforeEach(() => { view = mount(); });
afterEach(() => { view.unmount(); });

const SCENE = { pid: "p0007", name: "Kai", stage_words: "Dating", closeness_words: "Close", portrait: "" };

describe("scene UI", () => {
  it("heads the companion card 'The morning after' for a morning scene, and only then", () => {
    view.render(<Companion person={{ ...SCENE, kind: "morning", id: "p0007@31.5" }} />);
    expect(byTestId(view.host, "rr-companion").textContent).toContain("The morning after");
    view.render(<Companion person={{ ...SCENE, kind: "your_place", id: "p0007@31.5" }} />);
    expect(byTestId(view.host, "rr-companion").textContent).not.toContain("The morning after");
  });

  it("draws the companion card with words, never a number (a planted sentinel absent)", () => {
    const person = { pid: "p0007", name: "Kai", stage_words: "Seeing each other", closeness_words: "Close",
                     portrait: "", warmth: 61.987654, trust: 7.7654321 };
    view.render(<Companion person={person} />);
    expect(view.host.textContent).toContain("Kai");
    expect(view.host.textContent).toContain("Seeing each other");
    expect(view.host.textContent).toContain("Close");
    expect(view.host.textContent).not.toContain("61.987654");
    expect(view.host.textContent).not.toContain("7.7654321");
  });

  it("shows the companion card in a scene and not outside one", () => {
    const inScene = worldState({ phone: phoneFixture({ phone: { scene: SCENE } }) });
    view.render(<World state={inScene} phoneUp={false} onChoose={() => {}} />);
    expect(byTestId(view.host, "rr-companion")).not.toBeNull();
    const out = worldState({ phone: phoneFixture({ phone: { scene: {} } }) });
    view.render(<World state={out} phoneUp={false} onChoose={() => {}} />);
    expect(byTestId(view.host, "rr-companion")).toBeNull();
  });

  it("offers the scene's choices through the row", () => {
    const state = worldState({ phone: phoneFixture({ phone: { scene: SCENE } }),
                               choices: [{ id: "m1", text: "Ask about their work" }] });
    view.render(<World state={state} phoneUp={false} onChoose={() => {}} />);
    expect(view.host.textContent).toContain("Ask about their work");
  });

  it("names the household, in words, outside a scene", () => {
    const household = { pid: "p0009", name: "Sam", where: "asleep", portrait: "", warmth: 61.987654, note: "SENT-4417" };
    const state = worldState({ phone: phoneFixture({ phone: { world: { household } } }) });
    view.render(<World state={state} phoneUp={false} onChoose={() => {}} />);
    expect(byTestId(view.host, "rr-household").textContent).toBe("Sam lives with you, and is asleep.");
    expect(view.host.textContent).not.toContain("61.987654");
    expect(view.host.textContent).not.toContain("SENT-4417");
    const none = worldState({ phone: phoneFixture({ phone: { world: { household: {} } } }) });
    view.render(<World state={none} phoneUp={false} onChoose={() => {}} />);
    expect(byTestId(view.host, "rr-household")).toBeNull();
  });
});

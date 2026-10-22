// @vitest-environment jsdom
// ui/tests/rr-world.test.jsx -- READ RECEIPTS' two layers (v0.23.0 T21, spec §14.1, §19.9).
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PlayScreen from "../src/stories/read-receipts/PlayScreen.jsx";
import World from "../src/stories/read-receipts/world/World.jsx";
import Buzz from "../src/stories/read-receipts/world/Buzz.jsx";
import { initialState, phoneUpOf, reduce } from "../src/stories/read-receipts/state.js";
import { phoneFixture } from "./fixtures/phone.js";
import { coreState, worldState } from "./fixtures/phone-harness.jsx";
import { button, byTestId, click, key, mount, typeInto } from "./helpers/dom.js";

let view;
beforeEach(() => { view = mount(); });
afterEach(() => { view.unmount(); vi.restoreAllMocks(); delete window.matchMedia; });

const wide = (yes) => { window.matchMedia = (q) => ({ matches: yes && q.includes("1200"), addEventListener() {}, removeEventListener() {} }); };
// New payload keys go INSIDE `phone` (phoneFixture's real signature; pre-flight F8).
const WORLD = (over = {}) => ({ phone_up: true, at_work: false, location: "Lounge", buzz: { count: 0, who: [] }, ...over });
const screen = (state, over = {}) => (
  <PlayScreen state={state} sessionId="s1" onAct={() => true} onChoose={() => {}} onOpenMenu={() => {}} onOpenSaves={() => {}} {...over} />
);

describe("world and phone layers", () => {
  it("greys the world's choices while the phone is up, side by side at 1200px", () => {
    wide(true);
    const phone = phoneFixture({ phone: { world: WORLD() } });
    view.render(screen(worldState({ phone, choices: [{ id: "c1", text: "Tidy up" }] })));
    const choice = button(view.host, /Tidy up/);
    expect(choice.disabled).toBe(true);
    expect(view.host.textContent).toContain("Put the phone down to act");
    expect(byTestId(view.host, "rr-phone-layer").className).toContain("beside");
  });

  it("covers the world at phone sizes, dimmed behind", () => {
    wide(false);
    const phone = phoneFixture({ phone: { world: WORLD() } });
    view.render(screen(worldState({ phone })));
    expect(byTestId(view.host, "rr-phone-layer").className).toContain("over");
    expect(byTestId(view.host, "rr-world-layer").className).toContain("dimmed");
  });

  it("sends put_down from the status bar through onAct", () => {
    const onAct = vi.fn(() => true);
    const phone = phoneFixture({ phone: { world: WORLD() } });
    view.render(screen(worldState({ phone }), { onAct }));
    click(button(view.host, "Put the phone down"));
    expect(onAct).toHaveBeenCalledWith({ action: "put_down", target: "", args: {}, text: "" });
  });

  it("shows a buzz banner with names and never a message (a planted sentinel absent)", () => {
    view.render(<Buzz buzz={{ count: 2, who: ["Kai", "Mo"], preview: "MSG-7c1e55" }} onPickUp={() => {}} />);
    expect(view.host.textContent).toContain("Kai");
    expect(view.host.textContent).toContain("Mo");
    expect(view.host.textContent).not.toContain("MSG-7c1e55");
  });

  it("never draws a notification's words on the world layer", () => {
    const phone = phoneFixture({ phone: { world: WORLD({ phone_up: false, buzz: { count: 2, who: ["Cole", "Yusuf"] } }) } });
    for (const n of phone.notifications) n.preview = "MSG-7c1e55";
    view.render(screen(worldState({ phone })));
    const layer = byTestId(view.host, "rr-world-layer");
    expect(layer.textContent).not.toContain("MSG-7c1e55");
    expect(layer.textContent).toContain("Cole");
  });

  it("sends a world choice through onChoose when the phone is down", () => {
    const onChoose = vi.fn();
    const choice = { id: "c1", text: "Tidy up" };
    view.render(<World state={worldState({ choices: [choice] })} phoneUp={false} onChoose={onChoose} />);
    click(button(view.host, /Tidy up/));
    expect(onChoose).toHaveBeenCalledWith(choice);
  });

  it("offers Put the phone down on the very first frame, and the note, not a silent failure", () => {
    // A new game starts with the phone UP (T11): the opening frame, before any action.
    const phone = phoneFixture({ phone: { world: WORLD({ location: "Your flat" }) } });
    const state = worldState({ phone, choices: [{ id: "o1", text: "Make coffee" }, { id: "o2", text: "Look out of the window" }] });
    view.render(screen({ ...state, story: initialState }));
    expect(button(view.host, "Put the phone down")).not.toBeNull();
    expect(view.host.textContent).toContain("Put the phone down to act");
    expect(button(view.host, /Make coffee/).disabled).toBe(true);
    expect(byTestId(view.host, "rr-world-layer").textContent).toContain("Your flat");
  });

  it("draws the scene's words and nothing else of the person", () => {
    const scene = { pid: "p0347", name: "Cole", stage_words: "seeing each other", closeness_words: "warming", portrait: "", warmth: "HID-31" };
    const phone = phoneFixture({ phone: { world: WORLD({ phone_up: false }), scene } });
    view.render(screen(worldState({ phone })));
    const text = byTestId(view.host, "rr-world-layer").textContent;
    for (const words of ["Cole", "seeing each other", "warming"]) expect(text).toContain(words);
    expect(text).not.toContain("HID-31");
  });

  it("hides the phone at phone sizes once it is down, and the buzz banner picks it up again", () => {
    wide(false);
    const phone = phoneFixture({ phone: { world: WORLD({ phone_up: false, buzz: { count: 1, who: ["Kai"] } }) } });
    view.render(screen(worldState({ phone })));
    expect(byTestId(view.host, "rr-phone-layer").className).toContain("down");
    expect(byTestId(view.host, "rr-world-layer").className).not.toContain("dimmed");
    click(button(view.host, "Pick it up"));
    expect(byTestId(view.host, "rr-phone-layer").className).toContain("up");
    expect(byTestId(view.host, "rr-world-layer").className).toContain("dimmed");
  });

  it("always offers a way back to the phone while it is down, buzz or none", () => {
    wide(false);
    const phone = phoneFixture({ phone: { world: WORLD({ phone_up: false }) } });
    view.render(screen(worldState({ phone })));
    expect(byTestId(view.host, "rr-buzz")).toBeNull();
    click(button(view.host, "Pick up the phone"));
    expect(byTestId(view.host, "rr-phone-layer").className).toContain("up");
  });

  it("raises the phone and tells the refusal when the server answers a world choice 409 phone_up", () => {
    wide(false);
    const phone = phoneFixture({ phone: { world: WORLD({ phone_up: false }) } });
    const down = worldState({ phone });
    view.render(screen(down));
    expect(byTestId(view.host, "rr-phone-layer").className).toContain("down");
    const story = reduce(initialState, { type: "SOCKET", event: "turn_error", payload: { message: "Put the phone down first.", busy: false, phone_up: true } });
    expect(story.upSeq).toBe(1);
    view.render(screen({ ...down, story }));
    expect(byTestId(view.host, "rr-phone-layer").className).toContain("up");
    expect(view.host.textContent).toContain("Put the phone down first.");
  });

  it("reads phone_up off the world section, true for a block with none", () => {
    expect(phoneUpOf({ world: { phone_up: false } })).toBe(false);
    expect(phoneUpOf({})).toBe(true);
    expect(phoneUpOf(null)).toBe(true);
    expect(coreState(phoneFixture()).world.phone.world.phone_up).toBe(true);
  });
});

describe("the status bar under 900px (T21 fix round)", () => {
  it("keeps the weekday and lets only 'Day N' go", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve } = await import("node:path");
    const css = readFileSync(resolve(process.cwd(), "src/stories/read-receipts/theme/read-receipts.css"), "utf8").replace(/\r\n/g, "\n");
    expect(css).toMatch(/@media \(max-width: 899\.98px\) \{\n  \.rr-status__n \{\n    display: none;/);
    view.render(screen(worldState({ phone: phoneFixture({ phone: { world: WORLD() } }) })));
    const day = view.host.querySelector(".rr-status__day");
    expect(day.firstChild.textContent).toBe("Tue");
    expect(day.querySelector(".rr-status__n").textContent).toContain("Day 2");
  });
});

describe("typing in the world (A4 W6)", () => {
  const down = () => worldState({ phone: phoneFixture({ phone: { world: WORLD({ phone_up: false }) } }) });
  it("offers a compose box while the phone is down, and sends the line as custom", () => {
    const onCustom = vi.fn();
    view.render(<World state={down()} phoneUp={false} onChoose={() => {}} onCustom={onCustom} />);
    const form = byTestId(view.host, "rr-compose");
    expect(form).not.toBeNull();
    typeInto(form.querySelector("input"), "make breakfast");
    click(button(form, "Send"));
    expect(onCustom).toHaveBeenCalledWith("make breakfast");
  });

  it("greys the compose box while the phone is up, with the note", () => {
    const state = worldState({ phone: phoneFixture({ phone: { world: WORLD({ phone_up: true }) } }) });
    view.render(<World state={state} phoneUp={true} onChoose={() => {}} onCustom={() => {}} />);
    const input = byTestId(view.host, "rr-compose").querySelector("input");
    expect(input.getAttribute("aria-disabled")).toBe("true");
    expect(input.readOnly).toBe(true);
    expect(input.placeholder).toContain("Put the phone down");
  });

  it("does not send an empty line", () => {
    const onCustom = vi.fn();
    view.render(<World state={down()} phoneUp={false} onChoose={() => {}} onCustom={onCustom} />);
    const form = byTestId(view.host, "rr-compose");
    expect(button(form, "Send").disabled).toBe(true);
    typeInto(form.querySelector("input"), "   ");
    click(button(form, "Send"));
    expect(onCustom).not.toHaveBeenCalled();
  });

  it("focuses the box on / while the world is forward, and not while the phone is up", () => {
    view.render(<World state={down()} phoneUp={false} onChoose={() => {}} onCustom={() => {}} />);
    key("/");
    expect(document.activeElement).toBe(byTestId(view.host, "rr-compose").querySelector("input"));
    document.activeElement.blur();
    view.render(<World state={down()} phoneUp={true} onChoose={() => {}} onCustom={() => {}} />);
    key("/");
    expect(document.activeElement).not.toBe(byTestId(view.host, "rr-compose").querySelector("input"));
  });

  it("draws no compose box when the screen is given no onCustom", () => {
    view.render(<World state={down()} phoneUp={false} onChoose={() => {}} />);
    expect(byTestId(view.host, "rr-compose")).toBeNull();
  });

  it("the whole screen forwards onCustom to the world", () => {
    const onCustom = vi.fn();
    view.render(screen(down(), { onCustom }));
    const form = byTestId(view.host, "rr-compose");
    typeInto(form.querySelector("input"), "go to the kitchen");
    click(button(form, "Send"));
    expect(onCustom).toHaveBeenCalledWith("go to the kitchen");
  });
});

describe("who else is here (A4 W9)", () => {
  const here = (rows) => worldState({ phone: phoneFixture({ phone: { world: WORLD({ phone_up: false, here: rows }) } }) });

  it("lists who is also here by name, never a number", () => {
    view.render(<World state={here([{ name: "Tomas", kind: "around" }, { name: "Sam", kind: "contact" }])}
                       phoneUp={false} onChoose={() => {}} onCustom={() => {}} />);
    const line = byTestId(view.host, "rr-also-here");
    expect(line.textContent).toBe("Also here: Sam, Tomas");
    expect(line.textContent).not.toMatch(/\d/);
  });

  it("draws no line with nobody here, or with no `here` key at all", () => {
    view.render(<World state={here([])} phoneUp={false} onChoose={() => {}} />);
    expect(byTestId(view.host, "rr-also-here")).toBeNull();
    view.render(<World state={worldState({ phone: phoneFixture({ phone: { world: WORLD({ phone_up: false }) } }) })}
                       phoneUp={false} onChoose={() => {}} />);
    expect(byTestId(view.host, "rr-also-here")).toBeNull();
  });

  it("shows only a row's name: a planted extra key never reaches the screen", () => {
    view.render(<World state={here([{ name: "Sam", kind: "contact", pid: "p4417", warmth: 61.98 }])}
                       phoneUp={false} onChoose={() => {}} />);
    const text = byTestId(view.host, "rr-world-layer") ? byTestId(view.host, "rr-world-layer").textContent : view.host.textContent;
    expect(text).not.toContain("p4417");
    expect(text).not.toContain("61.98");
    expect(byTestId(view.host, "rr-also-here").textContent).toBe("Also here: Sam");
  });
});

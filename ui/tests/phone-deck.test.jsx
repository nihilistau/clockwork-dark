// @vitest-environment jsdom
// ui/tests/phone-deck.test.jsx -- READ RECEIPTS' two dating apps (v0.22.0 T27, spec §18.2).
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FrontPorch from "../src/stories/read-receipts/apps/FrontPorch.jsx";
import Matchstick from "../src/stories/read-receipts/apps/Matchstick.jsx";
import { phoneFixture } from "./fixtures/phone.js";
import { button, byTestId, click, key, mount, pointer, typeInto } from "./helpers/dom.js";

let view;
beforeEach(() => { view = mount(); });
afterEach(() => view.unmount());

/** Hidden values planted on the shown card's person: each is a SENTINEL no real label could contain (F19). */
const HIDDEN = { warmth: 7311, interest: 6911, trust: 5821, ghosted: "zz-ghosted-sentinel",
                 archetype: "zz-archetype-sentinel", chemistry: 0.4271 };

describe("Matchstick deck", () => {
  it("swipes right on the → key and on drag", () => {
    const act = vi.fn();
    view.render(<Matchstick phone={phoneFixture()} act={act} />);
    key("ArrowRight");
    expect(act).toHaveBeenCalledWith({ action: "swipe", target: "p0004", args: { dir: "like" }, text: "" });
    act.mockClear();
    const card = byTestId(view.host, "card-p0004");
    pointer(card, "pointerdown", 100);
    pointer(card, "pointermove", 260);
    pointer(card, "pointerup", 260);
    expect(act).toHaveBeenCalledWith(expect.objectContaining({ args: { dir: "like" } }));
  });

  it("offers super only while one is left", () => {
    view.render(<Matchstick phone={phoneFixture({ superLeft: 0 })} act={vi.fn()} />);
    expect(button(view.host, /super/i)).toBeNull();
  });

  it("renders no hidden value and no hidden key", () => {
    // Scan for the planted VALUES and for keys as attributes or props -- never for English words,
    // which an ordinary "Interests" heading would trip (pre-flight F19).
    view.render(<Matchstick phone={phoneFixture({ hidden: HIDDEN })} act={vi.fn()} />);
    const html = view.host.innerHTML;
    for (const value of Object.values(HIDDEN)) expect(html).not.toContain(String(value));
    for (const name of Object.keys(HIDDEN)) {
      expect(view.host.querySelector(`[data-${name}], [${name}]`)).toBeNull();
    }
  });

  it("passes on ← and a left drag, super-likes on ↑, and leaves the keys alone while typing", () => {
    const act = vi.fn();
    view.render(<Matchstick phone={phoneFixture()} act={act} />);
    key("ArrowLeft");
    expect(act).toHaveBeenLastCalledWith({ action: "swipe", target: "p0004", args: { dir: "pass" }, text: "" });
    key("ArrowUp");
    expect(act).toHaveBeenLastCalledWith({ action: "swipe", target: "p0004", args: { dir: "super" }, text: "" });
    const card = byTestId(view.host, "card-p0004");
    pointer(card, "pointerdown", 300);
    pointer(card, "pointerup", 120);
    expect(act).toHaveBeenLastCalledWith(expect.objectContaining({ args: { dir: "pass" } }));
    // A short drag is no swipe.
    act.mockClear();
    pointer(card, "pointerdown", 100);
    pointer(card, "pointerup", 140);
    expect(act).not.toHaveBeenCalled();
    // Typing elsewhere: the arrow keys are the field's.
    const field = document.createElement("input");
    document.body.appendChild(field);
    key("ArrowRight", field);
    expect(act).not.toHaveBeenCalled();
    field.remove();
  });

  it("presses: the buttons swipe too, and nothing more goes while a swipe is answered", () => {
    const act = vi.fn();
    view.render(<Matchstick phone={phoneFixture()} act={act} />);
    click(button(view.host, "Like"));
    click(button(view.host, "Pass"));
    expect(act.mock.calls.map(([i]) => i.args.dir)).toEqual(["like", "pass"]);
    act.mockClear();
    const pending = { action: "swipe", target: "p0004", args: { dir: "like" }, text: "" };
    view.render(<Matchstick phone={phoneFixture()} act={act} pending={pending} />);
    key("ArrowRight");
    click(button(view.host, "Like"));
    expect(act).not.toHaveBeenCalled();
  });

  it("reads its own deck from the deck keyed by app, and offers no like when none is left", () => {
    view.render(<Matchstick phone={phoneFixture({ likesLeft: 0 })} act={vi.fn()} />);
    expect(byTestId(view.host, "card-p0004")).not.toBeNull();
    expect(button(view.host, "Like")).toBeNull();
    expect(button(view.host, "Pass")).not.toBeNull();
    expect(view.host.textContent).toContain("No likes left today");
  });

  it("lists matches and chats from the threads, and opens one", () => {
    const onOpenThread = vi.fn();
    view.render(<Matchstick phone={phoneFixture()} act={vi.fn()} onOpenThread={onOpenThread} />);
    click(view.host.querySelector('[role="tab"]:nth-child(3)'));
    click(byTestId(view.host, "chat-matchstick:p0347"));
    expect(onOpenThread).toHaveBeenCalledWith("matchstick:p0347");
    click(view.host.querySelector('[role="tab"]:nth-child(2)'));
    expect(byTestId(view.host, "chat-matchstick:p1527")).not.toBeNull(); // matched, no message yet
  });
});

describe("the deck's keys stand down (review I2)", () => {
  it("while core's menu or settings is up (blocked), and for a key aimed at a dialog", () => {
    const act = vi.fn();
    view.render(<Matchstick phone={phoneFixture()} act={act} blocked />);
    key("ArrowRight");
    key("ArrowLeft");
    expect(act).not.toHaveBeenCalled();
    view.render(<Matchstick phone={phoneFixture()} act={act} blocked={false} />);
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    const inMenu = document.createElement("button");
    dialog.appendChild(inMenu);
    document.body.appendChild(dialog);
    key("ArrowRight", inMenu);
    expect(act).not.toHaveBeenCalled();
    dialog.remove();
    key("ArrowRight"); // nothing focused: the deck's
    expect(act).toHaveBeenCalledTimes(1);
  });

  it("the tab row takes its own arrows: moving tabs swipes nothing", () => {
    const act = vi.fn();
    view.render(<Matchstick phone={phoneFixture()} act={act} />);
    const tabs = [...view.host.querySelectorAll('[role="tab"]')];
    key("ArrowRight", tabs[0]);
    expect(act).not.toHaveBeenCalled();
    const after = [...view.host.querySelectorAll('[role="tab"]')];
    expect(after[1].getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(after[1]);
    const panel = view.host.querySelector('[role="tabpanel"]');
    expect(panel.getAttribute("aria-labelledby")).toBe(after[1].id);
    expect(after[1].getAttribute("aria-controls")).toBe(panel.id);
  });
});

describe("Front Porch", () => {
  it("likes a prompt with a comment, and passes", () => {
    const act = vi.fn();
    const phone = phoneFixture();
    const card = phone.deck.front_porch.card;
    view.render(<FrontPorch phone={phone} act={act} />);
    click(button(view.host, new RegExp(`^Like answer: ${card.prompts[1].q}`)));
    typeInto(view.host.querySelector("textarea"), "  the seaweed, though  ");
    click(button(view.host, "Send like"));
    expect(act).toHaveBeenCalledWith({
      action: "like", target: card.pid, args: { on: "prompt_1", comment: "the seaweed, though" }, text: "",
    });
    expect(view.host.querySelector('[role="dialog"]')).toBeNull();
    click(button(view.host, "Pass"));
    expect(act).toHaveBeenLastCalledWith({ action: "pass", target: card.pid, args: {}, text: "" });
  });

  it("caps a comment at 140 characters", () => {
    view.render(<FrontPorch phone={phoneFixture()} act={vi.fn()} />);
    click(button(view.host, /^Like photo:/));
    typeInto(view.host.querySelector("textarea"), "x".repeat(141));
    expect(button(view.host, "Send like").disabled).toBe(true);
    expect(view.host.textContent).toContain("141/140");
    typeInto(view.host.querySelector("textarea"), "x".repeat(140));
    expect(button(view.host, "Send like").disabled).toBe(false);
  });

  it("likes back from Likes you, with the comment optional", () => {
    const act = vi.fn();
    const phone = phoneFixture();
    const row = phone.likes_you[0];
    view.render(<FrontPorch phone={phone} act={act} />);
    click(view.host.querySelector('[role="tab"]:nth-child(2)'));
    expect(view.host.textContent).toContain(row.comment);
    click(button(view.host, "Like back"));
    click(button(view.host.querySelector('[role="dialog"]'), "Like back"));
    expect(act).toHaveBeenCalledWith({ action: "like_back", target: row.pid, args: {}, text: "" });
  });

  it("keeps a like that never went, with its words, and retries it", () => {
    const act = vi.fn();
    const onRetry = vi.fn();
    const phone = phoneFixture();
    const lost = { action: "like", target: phone.deck.front_porch.card.pid, args: { on: "photo_0", comment: "nice view" }, text: "" };
    view.render(<FrontPorch phone={phone} act={act} notSent={lost} onRetry={onRetry} />);
    expect(view.host.querySelector("textarea").value).toBe("nice view");
    click(button(view.host, "Not sent — tap to retry"));
    expect(onRetry).toHaveBeenCalledWith(lost);
  });

  it("a lost like's retry keeps the 140 cap; the sheet is modal and Escape closes it", () => {
    const onRetry = vi.fn();
    const onClearNotSent = vi.fn();
    const phone = phoneFixture();
    const lost = { action: "like", target: phone.deck.front_porch.card.pid, args: { on: "photo_0", comment: "x" }, text: "" };
    view.render(<FrontPorch phone={phone} act={vi.fn()} notSent={lost} onRetry={onRetry} onClearNotSent={onClearNotSent} />);
    typeInto(view.host.querySelector("textarea"), "y".repeat(141));
    const retry = button(view.host, "Not sent — tap to retry");
    expect(retry.disabled).toBe(true);
    click(retry);
    expect(onRetry).not.toHaveBeenCalled();
    const dialog = view.host.querySelector('[role="dialog"]');
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    key("Escape", view.host.querySelector("textarea"));
    expect(onClearNotSent).toHaveBeenCalled();
  });

  it("a like's sheet takes focus and gives it back when Escape closes it", () => {
    view.render(<FrontPorch phone={phoneFixture()} act={vi.fn()} />);
    const heart = button(view.host, /^Like photo:/);
    heart.focus();
    click(heart);
    expect(document.activeElement).toBe(view.host.querySelector("textarea"));
    key("Escape", view.host.querySelector("textarea"));
    expect(view.host.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(button(view.host, /^Like photo:/));
  });

  it("renders no hidden value and no hidden key", () => {
    view.render(<FrontPorch phone={phoneFixture({ hidden: HIDDEN })} act={vi.fn()} />);
    const html = view.host.innerHTML;
    for (const value of Object.values(HIDDEN)) expect(html).not.toContain(String(value));
    for (const name of Object.keys(HIDDEN)) {
      expect(view.host.querySelector(`[data-${name}], [${name}]`)).toBeNull();
    }
  });
});

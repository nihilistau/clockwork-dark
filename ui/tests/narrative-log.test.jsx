// @vitest-environment jsdom
/**
 * The narrative log, rendered.
 *
 * One rule, and it is the one that broke: a turn's prose appears in the
 * document ONCE.
 *
 * It stopped being true when the sentence announcer was added. The announcer is
 * a `visually-hidden` live region holding the text a screen reader should hear,
 * it lived inside the log, and it never cleared -- so between one turn and the
 * next the paragraph was in the document twice. Invisible to a sighted player,
 * but not to a screen reader browsing the log, and not to anything reading the
 * DOM: measured live on the flagship across two consecutive turns as one
 * `.entry--narration` and one `.visually-hidden` holding the same 602
 * characters, which is what a playtest reported as narration rendering twice.
 *
 * The rest of the file guards the other half: `role="log"` is implicitly a
 * polite live region, so the container announced every entry itself on top of
 * the announcer -- and re-announced the streaming paragraph on every frame it
 * grew, which is precisely the behaviour the announcer exists to replace.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import NarrativeLog from "../src/core/parts/NarrativeLog.jsx";

const PROSE =
  "The tavern comes into view, a low-slung building of heavy timber. " +
  "Light leaks through the gaps in the heavy oak doorframe.";

let host;
let root;

beforeEach(() => {
  vi.useFakeTimers();
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  React.act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

/** Render, then let effects and their timers settle. */
function draw(entries) {
  React.act(() => root.render(<NarrativeLog entries={entries} />));
}

/**
 * Every element that RENDERS `text` -- leaves only, so a container that happens
 * to hold nothing else is not counted as a second copy of its own child.
 */
function copiesOf(text) {
  return [...host.querySelectorAll("*")].filter(
    (el) => el.childElementCount === 0 && el.textContent === text
  );
}

describe("the narrative log", () => {
  const finished = [{ id: "e1", kind: "narration", text: PROSE }];

  it("puts a finished paragraph in the document exactly once", () => {
    draw(finished);
    // While the announcement is live there is a second, hidden copy by design:
    // that is what a live region IS. It must not be inside the log.
    expect(host.querySelector(".log").textContent).toBe(PROSE);

    React.act(() => vi.advanceTimersByTime(2000));
    expect(copiesOf(PROSE)).toHaveLength(1);
    expect(copiesOf(PROSE)[0].className).toContain("entry--narration");
  });

  it("withdraws the announcement instead of leaving it in the page", () => {
    draw(finished);
    const region = host.querySelector(".visually-hidden[aria-live]");
    expect(region.textContent).toBe(PROSE);

    React.act(() => vi.advanceTimersByTime(2000));
    expect(region.textContent).toBe("");
  });

  it("keeps the announcer out of the log", () => {
    draw(finished);
    expect(host.querySelector(".log .visually-hidden")).toBeNull();
    expect(host.querySelector(".visually-hidden[aria-live]")).not.toBeNull();
  });

  it("does not let the log container announce on its own", () => {
    // role="log" carries an implicit aria-live="polite". Left implicit, the
    // container spoke every entry a second time and re-read the streaming
    // paragraph on every frame.
    draw(finished);
    const log = host.querySelector(".log");
    expect(log.getAttribute("role")).toBe("log");
    expect(log.getAttribute("aria-live")).toBe("off");
  });

  it("announces only finished sentences while the paragraph is streaming", () => {
    draw([{ id: "e1", kind: "narration", text: "It is late. The door swi", streaming: true }]);
    const region = host.querySelector(".visually-hidden[aria-live]");
    expect(region.textContent).toBe("It is late.");
    // The half-written clause is on screen, but unspoken until it finishes.
    expect(host.querySelector(".log").textContent).toContain("The door swi");
  });

  it("announces the tail once, not the whole paragraph again, when the entry closes", () => {
    draw([{ id: "e1", kind: "narration", text: "It is late.", streaming: true }]);
    React.act(() => vi.advanceTimersByTime(2000));

    draw([{ id: "e1", kind: "narration", text: "It is late. The door swings wide." }]);
    expect(host.querySelector(".visually-hidden[aria-live]").textContent).toBe(
      "The door swings wide."
    );
  });
});

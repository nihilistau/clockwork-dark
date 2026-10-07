// @vitest-environment jsdom
/**
 * The choice row's keyboard shortcuts.
 *
 * The number badges 1-4 are bound on `window`, and `Play` stays MOUNTED
 * underneath every overlay -- the map, the clue board, the journal, the
 * gallery, and the pause menu. So the listener went on firing behind all of
 * them: pressing "1" while the pause menu was open submitted a turn the player
 * could not see and had not chosen.
 *
 * `App` already computes a `blocked` flag for its own global listener. This is
 * the same flag threaded down, so there is exactly one answer to "is the screen
 * blocked" rather than two that can disagree.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ChoiceRow from "../src/core/parts/ChoiceRow.jsx";

const CHOICES = [
  { id: "a", text: "Follow the smoke" },
  { id: "b", text: "Wait for morning" },
];

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

function draw(props) {
  const onChoose = vi.fn();
  React.act(() =>
    root.render(<ChoiceRow choices={CHOICES} onChoose={onChoose} {...props} />),
  );
  return onChoose;
}

function press(key, init = {}) {
  React.act(() => {
    window.dispatchEvent(
      new window.KeyboardEvent("keydown", { key, bubbles: true, ...init }),
    );
  });
}

describe("ChoiceRow keyboard shortcuts", () => {
  it("submits the numbered choice on a plain screen", () => {
    const onChoose = draw({});
    press("1");
    expect(onChoose).toHaveBeenCalledWith(CHOICES[0]);
  });

  it("does nothing while an overlay or the pause menu owns the screen", () => {
    const onChoose = draw({ blocked: true });
    press("1");
    press("2");
    expect(onChoose).not.toHaveBeenCalled();
  });

  it("does nothing while a turn is running", () => {
    const onChoose = draw({ busy: true });
    press("1");
    expect(onChoose).not.toHaveBeenCalled();
  });

  it("ignores a digit typed into a text field", () => {
    const onChoose = draw({});
    const input = document.createElement("input");
    host.appendChild(input);
    React.act(() => {
      input.dispatchEvent(
        new window.KeyboardEvent("keydown", { key: "1", bubbles: true }),
      );
    });
    expect(onChoose).not.toHaveBeenCalled();
  });

  it("ignores modified keypresses, which belong to the browser", () => {
    const onChoose = draw({});
    press("1", { metaKey: true });
    press("1", { ctrlKey: true });
    press("1", { altKey: true });
    expect(onChoose).not.toHaveBeenCalled();
  });

  it("ignores a number with no choice behind it", () => {
    const onChoose = draw({});
    press("4");
    expect(onChoose).not.toHaveBeenCalled();
  });
});

describe("the choice list's scroll cue (v0.21.0 T7, T6 review issue A)", () => {
  it("marks the list while rows lie below its fold, and clears it at the end", () => {
    draw({});
    const list = host.querySelector(".choices");
    // jsdom has no layout: give the list a 44px window onto 120px of chips.
    Object.defineProperty(list, "clientHeight", { configurable: true, value: 44 });
    Object.defineProperty(list, "scrollHeight", { configurable: true, value: 120 });
    React.act(() => list.dispatchEvent(new window.Event("scroll")));
    expect(list.dataset.more).toBe("true");

    list.scrollTop = 76;
    React.act(() => list.dispatchEvent(new window.Event("scroll")));
    expect(list.dataset.more).toBeUndefined();
  });
});

describe("focus through a turn (F9)", () => {
  it("a busy row's buttons are aria-disabled, not disabled, so focus stays", () => {
    const onChoose = vi.fn();
    React.act(() => root.render(<ChoiceRow choices={CHOICES} busy onChoose={onChoose} />));
    const chip = host.querySelector(".chip");
    expect(chip.disabled).toBe(false);
    expect(chip.getAttribute("aria-disabled")).toBe("true");
    chip.focus();
    React.act(() => chip.click());
    expect(onChoose).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(chip);
  });
});

describe("focus after the turn (F9, T13 fix round 1)", () => {
  const NEXT = [
    { id: "c", text: "Cross the square" },
    { id: "d", text: "Knock at the bakery" },
  ];

  it("lands on the first new chip when the pressed one is replaced", () => {
    const onChoose = vi.fn();
    React.act(() => root.render(<ChoiceRow choices={CHOICES} busy={false} onChoose={onChoose} />));
    const pressed = [...host.querySelectorAll(".chip")][1];
    pressed.focus();
    React.act(() => root.render(<ChoiceRow choices={CHOICES} busy onChoose={onChoose} />));
    expect(document.activeElement).toBe(pressed);
    React.act(() => root.render(<ChoiceRow choices={NEXT} busy={false} onChoose={onChoose} />));
    expect(pressed.isConnected).toBe(false);
    expect(document.activeElement).toBe(host.querySelector(".chip"));
    expect(document.activeElement.textContent).toContain("Cross the square");
  });

  it("never takes focus the player moved out of the row during the turn", () => {
    const box = document.createElement("input");
    document.body.appendChild(box);
    try {
      React.act(() => root.render(<ChoiceRow choices={CHOICES} busy={false} onChoose={() => {}} />));
      host.querySelector(".chip").focus();
      React.act(() => root.render(<ChoiceRow choices={CHOICES} busy onChoose={() => {}} />));
      box.focus();
      React.act(() => root.render(<ChoiceRow choices={NEXT} busy={false} onChoose={() => {}} />));
      expect(document.activeElement).toBe(box);
    } finally {
      box.remove();
    }
  });

  it("moves nothing while the screen is blocked, nor when focus was never in the row", () => {
    React.act(() => root.render(<ChoiceRow choices={CHOICES} busy={false} onChoose={() => {}} />));
    host.querySelector(".chip").focus();
    React.act(() => root.render(<ChoiceRow choices={CHOICES} busy onChoose={() => {}} />));
    React.act(() => root.render(<ChoiceRow choices={NEXT} busy={false} blocked onChoose={() => {}} />));
    expect(document.activeElement).toBe(document.body);

    React.act(() => root.render(<ChoiceRow choices={CHOICES} busy onChoose={() => {}} />));
    React.act(() => root.render(<ChoiceRow choices={NEXT} busy={false} onChoose={() => {}} />));
    expect(document.activeElement).toBe(document.body);
  });
});

describe("final fix wave: focus that stayed, and the choose-again signal", () => {
  it("keeps focus on the pressed chip when the new choices keep its id (T13 re-review nit)", () => {
    React.act(() => root.render(<ChoiceRow choices={CHOICES} busy={false} onChoose={() => {}} />));
    const pressed = [...host.querySelectorAll(".chip")][1];
    pressed.focus();
    React.act(() => root.render(<ChoiceRow choices={CHOICES} busy onChoose={() => {}} />));
    React.act(() => root.render(<ChoiceRow choices={[...CHOICES]} busy={false} onChoose={() => {}} />));
    expect(pressed.isConnected).toBe(true);
    expect(document.activeElement).toBe(pressed);
  });

  it("a bumped focusSignal puts focus on the first chip, unless the player put it elsewhere", () => {
    React.act(() => root.render(<ChoiceRow choices={CHOICES} busy={false} onChoose={() => {}} focusSignal={0} />));
    expect(document.activeElement).toBe(document.body);
    React.act(() => root.render(<ChoiceRow choices={CHOICES} busy={false} onChoose={() => {}} focusSignal={1} />));
    expect(document.activeElement).toBe(host.querySelector(".chip"));

    const box = document.createElement("input");
    document.body.appendChild(box);
    try {
      box.focus();
      React.act(() => root.render(<ChoiceRow choices={CHOICES} busy={false} onChoose={() => {}} focusSignal={2} />));
      expect(document.activeElement).toBe(box);
    } finally {
      box.remove();
    }
  });
});

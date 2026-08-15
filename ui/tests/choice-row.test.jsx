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

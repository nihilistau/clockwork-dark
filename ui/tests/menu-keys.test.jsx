// @vitest-environment jsdom
// ui/tests/menu-keys.test.jsx -- the pause menu's key table lists only keys core binds for the story
// on screen (v0.22.0 T30 follow-up): a story with its own PlayScreen has no numbered choices and no
// core compose box, so "1 – 4" and "/" are not offered there.
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/core/api.js", () => ({ fetchGames: vi.fn(async () => ({ games: [] })) }));

import Menu from "../src/core/screens/Menu.jsx";
import { mount } from "./helpers/dom.js";

let view;
beforeEach(() => { view = mount(); });
afterEach(() => view.unmount());

const noop = () => {};
const props = {
  world: {}, banner: null, storyId: "s", overlays: [], saveId: "", connected: true, prefs: {},
  onChangePrefs: noop, onResume: noop, onSaveNow: async () => {}, onOpenSaves: noop, onOpenSettings: noop,
  onNewRun: noop, onAbandon: noop,
};

const text = () => document.body.textContent;

describe("the menu's keys", () => {
  it("lists the choice keys and the compose key for a story played through choices", () => {
    view.render(<Menu {...props} />);
    expect(text()).toContain("Take the numbered choice");
    expect(text()).toContain("Jump to the compose box");
    expect(text()).toContain("This menu, or close whatever is open");
  });

  it("leaves them out for a story with its own play screen", () => {
    view.render(<Menu {...props} playScreen />);
    expect(text()).not.toContain("Take the numbered choice");
    expect(text()).not.toContain("Jump to the compose box");
    expect(text()).toContain("This menu, or close whatever is open");
    expect(text()).toContain("Send what you typed");
  });
});

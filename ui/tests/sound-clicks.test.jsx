// @vitest-environment jsdom
import React, { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/core/parts/MicButton.jsx", () => ({ default: () => null }));
vi.mock("../src/core/api.js", () => ({ fetchGames: vi.fn(async () => ({ games: [] })) }));

import { CATALOG, gesture, installFakeAudio } from "./helpers/fake-audio.js";
import { click, key, mount, typeInto } from "./helpers/dom.js";
import { installCatalog, installClickSounds, resetSound, setLevels, soundLog } from "../src/core/sound/index.js";
import ChoiceRow from "../src/core/parts/ChoiceRow.jsx";
import Modal from "../src/core/parts/Modal.jsx";
import Menu from "../src/core/screens/Menu.jsx";
import Play from "../src/core/screens/Play.jsx";
import { initialState } from "../src/core/store.js";

const PREFS = { muted: false, soundMaster: 1, soundUi: 1, soundGame: 1, soundAlert: 1, soundPhone: 1, soundWorld: 1 };
const CAT = { ...CATALOG, limits: { ...CATALOG.limits, throttle_ms: 0 },
  events: [...CATALOG.events, "ui.toggle", "ui.open", "ui.close", "choice.pick", "choice.send", "game.save"],
  bind: { ...CATALOG.bind, "ui.toggle": "ui.click", "ui.open": "ui.click", "ui.close": "ui.click",
          "choice.pick": "game.turn", "choice.send": "game.turn", "game.save": "game.turn" } };
let view; let off;
beforeEach(() => { installFakeAudio(); resetSound({ logPlays: true }); installCatalog(CAT); gesture(); setLevels(PREFS); view = mount(); off = installClickSounds(document); });
afterEach(() => { off(); view.unmount(); resetSound(); });
// The press is deferred to a macrotask (T5), so a flush waits one.
const flush = () => React.act(async () => { await new Promise((r) => setTimeout(r, 5)); });
const events = () => soundLog().filter((r) => !r.dropped).map((r) => r.event);

describe("rule 3: one action, one sound", () => {
  it("a plain button presses; data-sound none is silent; a disabled one is silent; a checkbox toggles", async () => {
    view.render(<div><button>a</button><button data-sound="none">b</button><button disabled>c</button><input type="checkbox" /></div>);
    const [a, b, c] = view.host.querySelectorAll("button");
    // One flush per click: a press deferred in the same tick as another would see that one's play as its own
    // handler's (T5's callCount rule), which no real player's clicks do.
    click(a); await flush();
    click(b); await flush();
    click(c); await flush();
    click(view.host.querySelector("input"));
    await flush();
    expect(events()).toEqual(["ui.press", "ui.toggle"]);
  });

  it("a choice sounds once, pressed or keyed", async () => {
    const onChoose = vi.fn();
    view.render(<ChoiceRow choices={[{ id: "a", text: "Go left" }, { id: "b", text: "Go right" }]} onChoose={onChoose} busy={false} />);
    click(view.host.querySelector("button"));
    key("2");
    await flush();
    expect(onChoose).toHaveBeenCalledTimes(2);
    expect(events()).toEqual(["choice.pick", "choice.pick"]);
  });

  it("a button that opens a Modal plays ui.open alone (F17)", async () => {
    function Opener() {
      const [open, setOpen] = useState(false);
      return (<>
        <button onClick={() => setOpen(true)}>open</button>
        {open && <Modal title="T" onClose={() => setOpen(false)}>x</Modal>}
      </>);
    }
    view.render(<Opener />);
    click(view.host.querySelector("button"));
    await flush();
    expect(events()).toEqual(["ui.open"]);
  });

  it("one Modal giving way to another in the same action sounds ui.open alone; a plain close sounds ui.close", async () => {
    function Swap() {
      const [which, setWhich] = useState("menu");
      return (<>
        {which === "menu" && <Modal title="M" onClose={() => setWhich(null)}><button data-sound="none" onClick={() => setWhich("settings")}>go</button></Modal>}
        {which === "settings" && <Modal title="S" onClose={() => setWhich(null)}>x</Modal>}
      </>);
    }
    view.render(<Swap />);
    await flush();
    expect(events()).toEqual(["ui.open"]);
    click([...document.querySelectorAll("button")].find((b) => b.textContent === "go"));
    await flush();
    expect(events()).toEqual(["ui.open", "ui.open"]);
    click(document.querySelector('button[aria-label="Close"]'));
    await flush();
    expect(events()).toEqual(["ui.open", "ui.open", "ui.close"]);
  });

  it("a typed line sends once, by its button or by Enter (F21)", async () => {
    const onCustom = vi.fn();
    const state = { ...initialState, screen: "scene", sessionId: "s1", link: "live",
      world: { location_id: "x", location_name: "X", world_day: 1, time_of_day: "day" }, log: [], choices: [] };
    const noop = () => {};
    view.render(<Play state={state} story={{ slug: "probe", title: "Probe", overlays: [], onboarding: [] }} onChoose={noop}
      onCustom={onCustom} onRetry={noop} onOpenSaves={noop} onOpenSettings={noop} onOpenOverlay={noop} onOpenMenu={noop}
      onToggleReasoning={noop} composeRef={{ current: null }} />);
    typeInto(view.host.querySelector(".compose__input"), "look around");
    click(view.host.querySelector(".compose button[type=submit]"));
    typeInto(view.host.querySelector(".compose__input"), "wait");
    React.act(() => { view.host.querySelector("form.compose").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    await flush();
    expect(onCustom).toHaveBeenCalledTimes(2);
    expect(events()).toEqual(["choice.send", "choice.send"]);
  });

  it("'Write' saves with one sound (F21)", async () => {
    const noop = () => {};
    view.render(<Menu world={{}} banner={null} storyId="s" overlays={[]} saveId="save1" connected prefs={{}}
      onChangePrefs={noop} onResume={noop} onSaveNow={async () => {}} onOpenSaves={noop} onOpenSettings={noop}
      onNewRun={noop} onAbandon={noop} />);
    const opened = events().length;               // Menu is a Modal: its own ui.open already sounded on mount
    click([...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Write"));
    await flush();
    expect(events().slice(opened)).toEqual(["game.save"]);
  });
});

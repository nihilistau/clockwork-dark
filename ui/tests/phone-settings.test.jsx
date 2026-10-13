// @vitest-environment jsdom
// ui/tests/phone-settings.test.jsx -- READ RECEIPTS' Settings (v0.22.0 T29, spec §18.2, §15.1): the bios per
// dating app (600 characters), discovery shown and not changeable, Natter's receipts, and "Let time pass" --
// local only, a browser preference, and the idle wait it sends.
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PlayScreen from "../src/stories/read-receipts/PlayScreen.jsx";
import Settings from "../src/stories/read-receipts/settings/Settings.jsx";
import { IDLE_MS, LET_TIME_PASS_KEY, MAX_IN_A_ROW, readLetTimePass, writeLetTimePass } from "../src/stories/read-receipts/settings/letTimePass.js";
import { initialState } from "../src/stories/read-receipts/state.js";
import { phoneFixture } from "./fixtures/phone.js";
import { coreState, PID } from "./fixtures/phone-harness.jsx";
import { button, byTestId, click, mount, typeInto } from "./helpers/dom.js";

let view;
beforeEach(() => {
  view = mount();
  window.localStorage.clear();
});
afterEach(() => {
  view.unmount();
  vi.useRealTimers();
  vi.restoreAllMocks();
  setHidden(false);
  delete window.matchMedia;
});

/** jsdom's page visibility, as a browser reports it when the tab is hidden or shown again. */
let hidden = false;
Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
function setHidden(value) {
  hidden = value;
  React.act(() => document.dispatchEvent(new window.Event("visibilitychange")));
}

const WAIT = { action: "wait", target: "", args: { until: "15m" }, text: "" };
const waits = (fn) => fn.mock.calls.filter(([i]) => i.action === "wait");

describe("Settings", () => {
  it("edits a dating app's bio, up to 600 characters", () => {
    const act = vi.fn();
    view.render(<Settings phone={phoneFixture()} act={act} />);
    const box = view.host.querySelector("#rr-bio-matchstick");
    typeInto(box, "x".repeat(601));
    expect(view.host.textContent).toContain("601/600");
    const save = view.host.querySelector("#rr-bio-matchstick").closest("form").querySelector("button");
    expect(save.disabled).toBe(true);
    typeInto(box, "pub quiz captain, chip enthusiast");
    click(save);
    expect(act).toHaveBeenCalledWith({ action: "edit_profile", target: "matchstick", args: { field: "bio" }, text: "pub quiz captain, chip enthusiast" });
    expect(view.host.querySelector("#rr-bio-front_porch")).not.toBeNull();
    expect(view.host.querySelector("#rr-bio-texts")).toBeNull();
  });

  it("shows discovery and offers no way to change it", () => {
    view.render(<Settings phone={phoneFixture()} act={vi.fn()} />);
    const discovery = byTestId(view.host, "discovery");
    expect(discovery.textContent).toContain("25–38");
    expect(discovery.textContent).toContain("City");
    expect(discovery.querySelector("input, select, button")).toBeNull();
  });

  it("switches Natter's read receipts", () => {
    const act = vi.fn();
    view.render(<Settings phone={phoneFixture()} act={act} />);
    expect(byTestId(view.host, "receipts").checked).toBe(true);
    click(byTestId(view.host, "receipts"));
    expect(act).toHaveBeenCalledWith({ action: "set_receipts", target: "natter", args: { to: "off" }, text: "" });
    view.render(<Settings phone={phoneFixture({ phone: { settings: { receipts: false } } })} act={act} />);
    expect(byTestId(view.host, "receipts").checked).toBe(false);
  });

  it("hides Let time pass in hosted mode", () => {
    view.render(<Settings phone={phoneFixture({ phone: { auto_wait: false } })} act={vi.fn()} />);
    expect(byTestId(view.host, "let-time-pass")).toBeNull();
    expect(view.host.textContent).not.toContain("Let time pass");
    view.render(<Settings phone={phoneFixture()} act={vi.fn()} />);
    expect(byTestId(view.host, "let-time-pass")).not.toBeNull();
  });

  it("keeps the preference in the browser, and survives storage that refuses", () => {
    expect(readLetTimePass()).toBe(false);
    writeLetTimePass(true);
    expect(window.localStorage.getItem(LET_TIME_PASS_KEY)).toBe("on");
    expect(readLetTimePass()).toBe(true);
    vi.spyOn(window.Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(window.Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(readLetTimePass()).toBe(false);
    expect(() => writeLetTimePass(true)).not.toThrow();
  });
});

/** PlayScreen on the fixture, its slice under the test's control, opened onto Cole's thread. */
function Phone({ phone, story, onAct, blocked = false }) {
  return <PlayScreen state={coreState(phone, story)} sessionId="s1" onAct={onAct} onOpenMenu={() => {}} onOpenSaves={() => {}} blocked={blocked} />;
}

function typingPhone(overrides = {}) {
  const phone = phoneFixture({ phone: overrides });
  phone.threads = phone.threads.map((t) => (t.pid === PID ? { ...t, typing: true } : t));
  return phone;
}

/** Into Cole's thread by his notification, the open_thread answered (turnSeq 1). */
function openCole(phone, onAct, blocked = false) {
  view.render(<Phone phone={phone} story={initialState} onAct={onAct} />);
  click(byTestId(view.host, "notif-n3"));
  view.render(<Phone phone={phone} story={{ ...initialState, turnSeq: 1 }} onAct={onAct} blocked={blocked} />);
}

/** Each wait answered (a new turnSeq), the thread still typing. */
function answer(phone, onAct, n) {
  view.render(<Phone phone={phone} story={{ ...initialState, turnSeq: n }} onAct={onAct} />);
}

describe("Let time pass (spec §15.1)", () => {
  it("sends wait 15m after 30 s idle while someone types, local only", () => {
    vi.useFakeTimers();
    writeLetTimePass(true);
    const onAct = vi.fn(() => true);
    const phone = typingPhone();
    openCole(phone, onAct);
    React.act(() => vi.advanceTimersByTime(IDLE_MS - 1000));
    expect(waits(onAct)).toHaveLength(0);
    React.act(() => vi.advanceTimersByTime(1000));
    expect(waits(onAct)).toEqual([[WAIT]]);
    // Nothing more while that wait is unanswered.
    React.act(() => vi.advanceTimersByTime(IDLE_MS * 2));
    expect(waits(onAct)).toHaveLength(1);
    // Answered, still typing: it arms again.
    view.render(<Phone phone={phone} story={{ ...initialState, turnSeq: 2 }} onAct={onAct} />);
    React.act(() => vi.advanceTimersByTime(IDLE_MS));
    expect(waits(onAct)).toHaveLength(2);
  });

  it("a touch or a key starts the 30 s again", () => {
    vi.useFakeTimers();
    writeLetTimePass(true);
    const onAct = vi.fn(() => true);
    openCole(typingPhone(), onAct);
    React.act(() => vi.advanceTimersByTime(IDLE_MS - 5000));
    React.act(() => view.host.querySelector("textarea").dispatchEvent(new window.KeyboardEvent("keydown", { key: "h", bubbles: true })));
    React.act(() => vi.advanceTimersByTime(IDLE_MS - 5000));
    expect(waits(onAct)).toHaveLength(0);
    React.act(() => vi.advanceTimersByTime(5000));
    expect(waits(onAct)).toHaveLength(1);
  });

  it("sends nothing when off, in hosted mode, or when nobody is typing or due", () => {
    vi.useFakeTimers();
    const onAct = vi.fn(() => true);
    openCole(typingPhone(), onAct);                                     // the preference is off
    React.act(() => vi.advanceTimersByTime(IDLE_MS * 3));
    writeLetTimePass(true);
    view.unmount();
    view = mount();
    openCole(typingPhone({ auto_wait: false }), onAct);                 // hosted: the payload says no
    React.act(() => vi.advanceTimersByTime(IDLE_MS * 3));
    view.unmount();
    view = mount();
    openCole(phoneFixture(), onAct);                                     // nobody typing, nothing due
    React.act(() => vi.advanceTimersByTime(IDLE_MS * 3));
    expect(waits(onAct)).toHaveLength(0);
  });

  it("watches a reply on its way ('…') as well as typing, and is switched from Settings", () => {
    vi.useFakeTimers();
    const onAct = vi.fn(() => true);
    const phone = phoneFixture();
    phone.threads = phone.threads.map((t) => (t.pid === PID ? { ...t, last: { ...t.last, pending: true } } : t));
    view.render(<Phone phone={phone} story={initialState} onAct={onAct} />);
    click(button(view.host, "Open phone"));
    click(byTestId(view.host, "app-settings"));
    click(byTestId(view.host, "let-time-pass"));
    expect(window.localStorage.getItem(LET_TIME_PASS_KEY)).toBe("on");
    click(button(view.host, "Home"));
    click(byTestId(view.host, "app-matchstick"));
    click(view.host.querySelector('[role="tab"]:nth-child(3)'));
    click(byTestId(view.host, `chat-matchstick:${PID}`));
    view.render(<Phone phone={phone} story={{ ...initialState, turnSeq: 1 }} onAct={onAct} />);
    React.act(() => vi.advanceTimersByTime(IDLE_MS));
    expect(waits(onAct)).toEqual([[WAIT]]);
  });

  it("time can always be passed by hand: the status bar's Lock, then Put it down", () => {
    const onAct = vi.fn(() => true);
    openCole(phoneFixture(), onAct);
    click(button(view.host, "Lock"));
    click(button(view.host, "Put it down"));
    expect(onAct).toHaveBeenLastCalledWith({ action: "wait", target: "", args: { until: "next" }, text: "" });
  });
});

describe("Let time pass only while watched (T29 review I1, M1, M2)", () => {
  it("sends nothing while the page is hidden, and arms again when it is shown", () => {
    vi.useFakeTimers();
    writeLetTimePass(true);
    const onAct = vi.fn(() => true);
    openCole(typingPhone(), onAct);
    React.act(() => vi.advanceTimersByTime(IDLE_MS - 5000));
    setHidden(true);
    React.act(() => vi.advanceTimersByTime(IDLE_MS * 10));
    expect(waits(onAct)).toHaveLength(0);
    setHidden(false);
    React.act(() => vi.advanceTimersByTime(IDLE_MS - 1));
    expect(waits(onAct)).toHaveLength(0);                       // a fresh 30 s, not the old timer's last 5
    React.act(() => vi.advanceTimersByTime(1));
    expect(waits(onAct)).toHaveLength(1);
  });

  it(`stops after ${MAX_IN_A_ROW} waits in a row with no input, and an input starts the count again`, () => {
    vi.useFakeTimers();
    writeLetTimePass(true);
    const onAct = vi.fn(() => true);
    const phone = typingPhone();
    openCole(phone, onAct);
    for (let n = 2; n < 2 + MAX_IN_A_ROW + 3; n += 1) {
      React.act(() => vi.advanceTimersByTime(IDLE_MS));
      answer(phone, onAct, n);
    }
    expect(waits(onAct)).toHaveLength(MAX_IN_A_ROW);           // one in-game hour, then it waits for the player
    React.act(() => view.host.querySelector(".rr").dispatchEvent(new window.MouseEvent("pointerdown", { bubbles: true })));
    React.act(() => vi.advanceTimersByTime(IDLE_MS));
    expect(waits(onAct)).toHaveLength(MAX_IN_A_ROW + 1);
  });

  it("sends nothing while core's menu is up (blocked)", () => {
    vi.useFakeTimers();
    writeLetTimePass(true);
    const onAct = vi.fn(() => true);
    openCole(typingPhone(), onAct, true);
    React.act(() => vi.advanceTimersByTime(IDLE_MS * 3));
    expect(waits(onAct)).toHaveLength(0);
  });

  it("sends nothing while a confirm is open in the phone", () => {
    vi.useFakeTimers();
    writeLetTimePass(true);
    const onAct = vi.fn(() => true);
    const meet = { id: "t1", pid: PID, name: "Cole", venue: "the_anchor", venue_label: "The Anchor", when: "Tue 19:00",
      status: "agreed", start: 60, end: 62.5 };
    openCole(typingPhone({ calendar: [meet] }), onAct);
    // The click that opens it is an input: no pointerdown here, so only the open confirm can hold the wait.
    click(button(byTestId(view.host, "meet-t1"), "Cancel"));
    expect(view.host.querySelector('[role="alertdialog"]')).not.toBeNull();
    React.act(() => vi.advanceTimersByTime(IDLE_MS * 3));
    expect(waits(onAct)).toHaveLength(0);
    click(button(view.host, "Keep it"));
    React.act(() => vi.advanceTimersByTime(IDLE_MS));
    expect(waits(onAct)).toHaveLength(1);
  });

  it("counts input anywhere on the phone's frame, the side sheet included", () => {
    vi.useFakeTimers();
    window.matchMedia = (query) => ({ matches: query === "(min-width: 1200px)", addEventListener() {}, removeEventListener() {} });
    writeLetTimePass(true);
    const onAct = vi.fn(() => true);
    openCole(typingPhone(), onAct);
    click(button(view.host, "About Cole"));
    const side = view.host.querySelector(".rr-side");
    expect(side).not.toBeNull();
    React.act(() => vi.advanceTimersByTime(IDLE_MS - 1000));
    React.act(() => side.querySelector("button").dispatchEvent(new window.KeyboardEvent("keydown", { key: "Tab", bubbles: true })));
    React.act(() => vi.advanceTimersByTime(IDLE_MS - 1000));
    expect(waits(onAct)).toHaveLength(0);
    React.act(() => vi.advanceTimersByTime(1000));
    expect(waits(onAct)).toHaveLength(1);
  });
});

describe("the bio's cap is the payload's (review M10)", () => {
  it("counts to settings.bio_max", () => {
    view.render(<Settings phone={phoneFixture({ phone: { settings: { receipts: true, bio_max: 40 } } })} act={vi.fn()} />);
    typeInto(view.host.querySelector("#rr-bio-matchstick"), "x".repeat(41));
    expect(view.host.textContent).toContain("41/40");
    expect(view.host.querySelector("#rr-bio-matchstick").closest("form").querySelector("button").disabled).toBe(true);
  });
});

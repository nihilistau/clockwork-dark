// @vitest-environment jsdom
// ui/tests/phone-settings.test.jsx -- READ RECEIPTS' Settings (v0.22.0 T29, spec §18.2): the bios per
// dating app (600 characters), discovery shown and not changeable, Natter's receipts and (v0.23.0 T22)
// "Wake me for messages". "Let time pass" is gone (v0.23.0): its tests were removed with it -- "sends wait
// 15m after 30 s idle while someone types", "a touch or a key starts the 30 s again", "sends nothing when
// off, in hosted mode, or when nobody is typing or due", "watches a reply on its way as well as typing",
// "time can always be passed by hand", "hides Let time pass in hosted mode", "keeps the preference in the
// browser", and the five "only while watched" tests (hidden page, the in-a-row cap, core's menu, an open
// confirm, input anywhere on the frame).
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Settings from "../src/stories/read-receipts/settings/Settings.jsx";
import { phoneFixture } from "./fixtures/phone.js";
import { byTestId, click, mount, typeInto } from "./helpers/dom.js";

let view;
beforeEach(() => { view = mount(); });
afterEach(() => {
  view.unmount();
  vi.restoreAllMocks();
});

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

  it("has no Let time pass, whatever the payload says", () => {
    view.render(<Settings phone={phoneFixture({ phone: { auto_wait: true } })} act={vi.fn()} />);
    expect(view.host.textContent).not.toContain("Let time pass");
    expect(byTestId(view.host, "let-time-pass")).toBeNull();
  });

  it("toggles Wake me for messages through set_wake, and shows the engine's word on it", () => {
    const act = vi.fn();
    view.render(<Settings phone={phoneFixture()} act={act} />);
    expect(view.host.textContent).toContain("Wake me for messages");
    expect(byTestId(view.host, "wake-for-messages").checked).toBe(false);          // off by default
    click(byTestId(view.host, "wake-for-messages"));
    expect(act).toHaveBeenCalledWith({ action: "set_wake", target: "", args: { to: "on" }, text: "" });
    view.render(<Settings phone={phoneFixture({ phone: { settings: { receipts: true, wake_for_messages: true } } })} act={act} />);
    expect(byTestId(view.host, "wake-for-messages").checked).toBe(true);
    click(byTestId(view.host, "wake-for-messages"));
    expect(act).toHaveBeenLastCalledWith({ action: "set_wake", target: "", args: { to: "off" }, text: "" });
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

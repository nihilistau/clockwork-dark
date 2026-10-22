// @vitest-environment jsdom
// ui/tests/phone-contact.test.jsx -- READ RECEIPTS' contact card (v0.22.0 T29, spec §18.2-18.3), and the
// Contacts, Photos and Calendar apps: what the card shows (the player's view, never what they know of the
// player), its confirms, the plan sheet (a plan has no set time, v0.23.0 T22), starting a game, the side sheet at 1200px and
// over, and the hidden-value scan over all four.
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Calendar from "../src/stories/read-receipts/calendar/Calendar.jsx";
import ContactCard, { heardWords } from "../src/stories/read-receipts/contact/ContactCard.jsx";
import Contacts from "../src/stories/read-receipts/contact/Contacts.jsx";
import Photos from "../src/stories/read-receipts/photos/Photos.jsx";
import { phoneFixture, plantHidden } from "./fixtures/phone.js";
import { Harness, PID } from "./fixtures/phone-harness.jsx";
import { button, byTestId, byText, click, key, mount } from "./helpers/dom.js";

let view;
beforeEach(() => { view = mount(); });
afterEach(() => {
  view.unmount();
  delete window.matchMedia;
});

const cole = (phone) => phone.contacts.find((c) => c.pid === PID);
const card = (props = {}) => {
  const phone = props.phone || phoneFixture();
  return <ContactCard contact={cole(phone)} phone={phone} act={props.act || vi.fn()} onBack={vi.fn()} onOpenThread={props.onOpenThread || vi.fn()} />;
};
const selectValue = (select, value) => React.act(() => {
  select.value = String(value);
  select.dispatchEvent(new window.Event("change", { bubbles: true }));
});

describe("the contact card", () => {
  it("shows their photos and profile, the stage's words and band, your story and what they've told you", () => {
    view.render(card());
    expect(view.host.querySelector(".rr-photo__caption").textContent).toBe("laughing at a pub table");
    click(button(view.host, "Next photo"));
    expect(view.host.querySelector(".rr-photo__caption").textContent).toBe("on a beach at sunset");
    expect(byTestId(view.host, "contact-stage").textContent).toBe("Just matchedNew");
    expect(view.host.textContent).toContain("31 · Electrician · The Quays");
    expect(view.host.textContent).toContain("here for the pub quiz, staying for the chips");
    expect(view.host.textContent).toContain("Last heard from today.");
    expect([...byTestId(view.host, "contact-story").querySelectorAll(".rr-story__what")].map((el) => el.textContent))
      .toEqual(["Matched on Matchstick", "First message"]);
    expect(byTestId(view.host, "contact-about").textContent).toBe("I'm a terrible cook but a great washer-upper");
    // Never a number for where things stand.
    expect(byTestId(view.host, "contact-stage").textContent).not.toMatch(/\d/);
  });

  it("words how long since you heard from them", () => {
    expect(heardWords(null)).toBe("You haven't heard from them yet.");
    expect(heardWords(1)).toBe("Last heard from yesterday.");
    expect(heardWords(4)).toBe("Last heard from 4 days ago.");
  });

  it("confirms before block", () => {
    const act = vi.fn();
    view.render(card({ act }));
    const block = button(view.host, "Block");
    block.focus();
    click(block);
    expect(byTestId(view.host, "confirm-block").textContent).toContain("Block Cole?");
    expect(document.activeElement.textContent).toBe("Cancel");
    click(button(view.host, "Cancel"));
    expect(act).not.toHaveBeenCalled();
    expect(byTestId(view.host, "confirm-block")).toBeNull();
    expect(document.activeElement.textContent).toBe("Block");
    click(button(view.host, "Block"));
    click(byTestId(view.host, "confirm-block").querySelector(".rr-btn--danger"));
    expect(act).toHaveBeenCalledWith({ action: "block", target: PID, args: {}, text: "" });
  });

  it("unmatches and ends things behind their own confirms", () => {
    const act = vi.fn();
    view.render(card({ act }));
    click(button(view.host, "Unmatch"));
    click(byTestId(view.host, "confirm-unmatch").querySelector(".rr-btn--danger"));
    expect(act).toHaveBeenLastCalledWith({ action: "unmatch", target: PID, args: {}, text: "" });
    click(button(view.host, "End things"));
    click(byTestId(view.host, "confirm-end").querySelector(".rr-btn--danger"));
    expect(act).toHaveBeenLastCalledWith({ action: "end", target: PID, args: {}, text: "" });
  });

  it("offers no unmatch once there is no match, and only Block once nothing is open", () => {
    const phone = phoneFixture();
    cole(phone).matched = false;
    view.render(card({ phone }));
    expect(button(view.host, "Unmatch")).toBeNull();
    cole(phone).open = false;
    view.render(card({ phone: { ...phone } }));
    expect(button(view.host, "End things")).toBeNull();
    expect(button(view.host, "Ask to meet")).toBeNull();
    expect(button(view.host, "Block")).not.toBeNull();
  });

  it("asks to meet through the plan sheet, with a time of day and no set time (v0.23.0)", () => {
    const act = vi.fn();
    view.render(card({ act }));
    click(button(view.host, "Ask to meet"));
    expect(byTestId(view.host, "plan-day")).toBeNull();                 // no day, no slot: the v0.22 planner is gone
    expect(byTestId(view.host, "plan-slot")).toBeNull();
    expect([...byTestId(view.host, "plan-venue").options].map((o) => o.textContent)).toEqual(
      ["Wherever suits", "Coffee at The Copper Kettle", "Drinks at The Anchor"]);
    selectValue(byTestId(view.host, "plan-kind"), "drinks");
    selectValue(byTestId(view.host, "plan-venue"), "the_anchor");
    click(button(view.host, "Tonight?"));
    expect(act).toHaveBeenCalledWith({ action: "ask", target: `matchstick:${PID}`,
      args: { what: "meet", when: "tonight", kind: "drinks", venue: "the_anchor" }, text: "" });
  });

  it("starts a game and opens the chat", () => {
    const act = vi.fn();
    const onOpenThread = vi.fn();
    view.render(card({ act, onOpenThread }));
    click(button(view.host, "Play Tile Talk"));
    expect(act).toHaveBeenCalledWith({ action: "game_invite", target: PID, args: { game: "wordgame" }, text: "" });
    click(button(view.host, "Message"));
    expect(onOpenThread).toHaveBeenCalledWith(`matchstick:${PID}`);
  });
});

describe("where the card opens", () => {
  it("inside the phone under 1200px, from the thread's header, and Back returns to the thread", () => {
    view.render(<Harness onAct={vi.fn(() => true)} />);
    click(button(view.host, "About Cole"));
    expect(view.host.querySelector(".rr-view .rr-contact")).not.toBeNull();
    expect(view.host.querySelector(".rr-side")).toBeNull();
    expect(document.activeElement.textContent).toBe("Cole");
    click(button(view.host, "Back"));
    expect(view.host.querySelector(".rr-thread")).not.toBeNull();
  });

  it("as a side sheet beside the phone at 1200px and over, the thread staying on screen", () => {
    window.matchMedia = (query) => ({ matches: query === "(min-width: 1200px)", addEventListener() {}, removeEventListener() {} });
    view.render(<Harness onAct={vi.fn(() => true)} />);
    button(view.host, "About Cole").focus();          // a real click focuses the button it presses
    click(button(view.host, "About Cole"));
    const side = view.host.querySelector(".rr-side");
    expect(side).not.toBeNull();
    expect(side.querySelector(".rr-contact")).not.toBeNull();
    expect(view.host.querySelector(".rr-view .rr-thread")).not.toBeNull();
    expect(side.contains(document.activeElement)).toBe(true);
    click(button(side, "Close"));
    expect(view.host.querySelector(".rr-side")).toBeNull();
    expect(document.activeElement).toBe(button(view.host, "About Cole"));
  });

  it("from the Contacts app", () => {
    const onOpenContact = vi.fn();
    view.render(<Contacts phone={phoneFixture()} onOpenContact={onOpenContact} />);
    expect(byTestId(view.host, `contact-row-${PID}`).textContent).toContain("Just matched");
    click(byTestId(view.host, `contact-row-${PID}`));
    expect(onOpenContact).toHaveBeenCalledWith(PID);
  });
});

describe("Photos and Calendar", () => {
  const photo = { mid: "x4", kind: "photo", status: "fallback", url: "", poster_url: "", caption: "the view from the climb", pid: PID,
    name: "Cole", thread_id: `matchstick:${PID}`, message_id: "m9", at: 40.5 };

  it("Photos: the camera roll and what people sent, which opens its chat", () => {
    const onOpenThread = vi.fn();
    view.render(<Photos phone={phoneFixture({ phone: { gallery: [photo, { ...photo, mid: "x5", kind: "video", status: "ready", url: "https://evil.example/x.mp4" }] } })} onOpenThread={onOpenThread} />);
    expect(byTestId(view.host, "roll-climbing_wall").textContent).toContain("halfway up a climbing wall");
    click(view.host.querySelectorAll('[role="tab"]')[1]);
    expect(byTestId(view.host, "photo-x4").textContent).toContain("the view from the climb");
    expect(view.host.querySelector("video")).toBeNull();                  // not the media route: no file
    click(button(view.host, /^Cole/));
    expect(onOpenThread).toHaveBeenCalledWith(`matchstick:${PID}`);
  });

  it("Calendar: Coming up lists open plans and promises in words, and what is past", () => {
    const plan = { id: "pl1", pid: PID, name: "Cole", kind: "drinks", venue: "the_anchor", venue_label: "The Anchor",
      place: "Drinks at The Anchor", when: "tonight", words: "Drinks at The Anchor, tonight", by: "player" };
    const open = { id: "pr1", pid: PID, name: "Cole", by: "person", window_words: "in the morning", opens_at_words: "07:00", status: "open" };
    const kept = { id: "pr0", pid: PID, name: "Cole", by: "player", window_words: "at lunch", opens_at_words: "now", status: "kept" };
    const onOpenContact = vi.fn();
    view.render(<Calendar phone={phoneFixture({ phone: { plans: [plan], promises: [kept, open] } })} onOpenContact={onOpenContact} />);
    expect(byText(view.host, "Coming up")).not.toBeNull();
    expect(byTestId(view.host, "plan-pl1").textContent).toContain("Drinks at The Anchor, tonight");
    expect(byTestId(view.host, "promise-pr1").textContent).toContain("Cole will message you in the morning");
    expect(byTestId(view.host, "promise-pr0").textContent).toContain("You'll message Cole at lunch");
    expect(byTestId(view.host, "promise-pr0").textContent).toContain("Kept");
    expect(byText(view.host, "Before")).not.toBeNull();
    click(button(byTestId(view.host, "plan-pl1"), "With Cole"));
    expect(onOpenContact).toHaveBeenCalledWith(PID);
    for (const list of view.host.querySelectorAll("ul")) for (const child of list.children) expect(child.tagName).toBe("LI");
  });

  it("Calendar: nothing planned says so", () => {
    view.render(<Calendar phone={phoneFixture()} />);
    expect(view.host.textContent).toContain("Nothing planned.");
  });
});

describe("hidden values in the contact card, Contacts, Photos and Calendar (spec §17.3)", () => {
  const HIDDEN = { warmth: 7311, interest: 6911, trust: 5821, ghosted: "zz-ghosted-sentinel", mood: "zz-mood-sentinel",
    knows: "zz-knows-sentinel", flake: "zz-flake-sentinel", quality: 0.4271, archetype: "zz-archetype-sentinel" };
  const clean = () => {
    const html = view.host.innerHTML;
    for (const value of Object.values(HIDDEN)) expect(html).not.toContain(String(value));
    for (const name of Object.keys(HIDDEN)) expect(view.host.querySelector("[data-" + name + "], [" + name + "]")).toBeNull();
  };
  it("draws none", () => {
    const plan = { id: "pl1", pid: PID, name: "Cole", kind: "drinks", venue: "the_anchor", venue_label: "The Anchor",
      place: "Drinks at The Anchor", when: "tonight", words: "Drinks at The Anchor, tonight", by: "player" };
    const promise = { id: "pr1", pid: PID, name: "Cole", by: "person", window_words: "in the morning", opens_at_words: "07:00", status: "open" };
    const photo = { mid: "x4", kind: "photo", status: "fallback", url: "", poster_url: "", caption: "a view", pid: PID, name: "Cole",
      thread_id: `matchstick:${PID}`, message_id: "m9", at: 40.5 };
    const phone = plantHidden(phoneFixture({ phone: { plans: [plan], promises: [promise], gallery: [photo] } }), HIDDEN);
    view.render(<ContactCard contact={cole(phone)} phone={phone} act={vi.fn()} onBack={vi.fn()} onOpenThread={vi.fn()} />);
    expect(view.host.querySelector(".rr-story__row")).not.toBeNull();
    clean();
    click(button(view.host, "Ask to meet"));
    clean();
    view.render(<Contacts phone={phone} onOpenContact={vi.fn()} />);
    clean();
    view.render(<Photos phone={phone} onOpenThread={vi.fn()} />);
    click(view.host.querySelectorAll('[role="tab"]')[1]);
    expect(byTestId(view.host, "photo-x4")).not.toBeNull();
    clean();
    view.render(<Calendar phone={phone} />);
    expect(byTestId(view.host, "plan-pl1")).not.toBeNull();
    clean();
  });
});

describe("review fixes (M5-M8)", () => {
  const wide = () => {
    window.matchMedia = (query) => ({ matches: query === "(min-width: 1200px)", addEventListener() {}, removeEventListener() {} });
  };

  it("a confirm is described by its question and closes on Escape, sending nothing and keeping core's menu shut", () => {
    const act = vi.fn();
    const menu = vi.fn();
    window.addEventListener("keydown", menu);
    try {
      view.render(card({ act }));
      const block = button(view.host, "Block");
      block.focus();
      click(block);
      const dialog = byTestId(view.host, "confirm-block");
      expect(document.getElementById(dialog.getAttribute("aria-describedby")).textContent).toBe(
        "Block Cole? They won't be able to reach you anywhere on the phone.");
      key("Escape", document.activeElement);
      expect(byTestId(view.host, "confirm-block")).toBeNull();
      expect(document.activeElement.textContent).toBe("Block");
      expect(act).not.toHaveBeenCalled();
      expect(menu).not.toHaveBeenCalled();                          // the Escape stayed in the phone
    } finally {
      window.removeEventListener("keydown", menu);
    }
  });

  it("the side sheet starts fresh for another person (key={sheet})", () => {
    wide();
    const phone = phoneFixture();
    phone.contacts.push({ ...cole(phone), pid: "p1190", name: "Yusuf", thread_ids: ["matchstick:p1190"] });
    view.render(<Harness onAct={vi.fn(() => true)} phone={phone} />);
    click(button(view.host, "About Cole"));
    click(button(view.host.querySelector(".rr-side"), "Block"));
    expect(byTestId(view.host, "confirm-block")).not.toBeNull();
    // Contacts, in the phone, while the sheet is open: Yusuf's card replaces Cole's, with no confirm carried over.
    click(button(view.host, "Home"));
    click(byTestId(view.host, "app-contacts"));
    click(byTestId(view.host, "contact-row-p1190"));
    expect(view.host.querySelector(".rr-side .rr-contact__name").textContent).toBe("Yusuf");
    expect(byTestId(view.host, "confirm-block")).toBeNull();
  });

  it("closing a sheet opened from the Calendar returns focus to that entry", () => {
    wide();
    const plan = { id: "pl1", pid: PID, name: "Cole", kind: "drinks", venue: "the_anchor", venue_label: "The Anchor",
      place: "Drinks at The Anchor", when: "tonight", words: "Drinks at The Anchor, tonight", by: "player" };
    view.render(<Harness onAct={vi.fn(() => true)} phone={phoneFixture({ phone: { plans: [plan] } })} />);
    click(button(view.host, "Home"));
    click(byTestId(view.host, "app-calendar"));
    const entry = button(view.host, "With Cole");
    entry.focus();
    click(entry);
    click(button(view.host.querySelector(".rr-side"), "Close"));
    expect(document.activeElement).toBe(button(view.host, "With Cole"));
  });
});

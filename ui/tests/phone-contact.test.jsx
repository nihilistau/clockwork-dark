// @vitest-environment jsdom
// ui/tests/phone-contact.test.jsx -- READ RECEIPTS' contact card (v0.22.0 T29, spec §18.2-18.3), and the
// Contacts, Photos and Calendar apps: what the card shows (the player's view, never what they know of the
// player), its confirms, the meet-up planner's seven days, starting a game, the side sheet at 1200px and
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
    expect(button(view.host, "Plan a meet-up")).toBeNull();
    expect(button(view.host, "Block")).not.toBeNull();
  });

  it("plans a meet-up with day +1..+7 only", () => {
    const act = vi.fn();
    view.render(card({ act }));
    click(button(view.host, "Plan a meet-up"));
    const days = byTestId(view.host, "plan-day");
    expect([...days.options].map((o) => o.value)).toEqual(["1", "2", "3", "4", "5", "6", "7"]);
    expect(days.options[0].textContent).toBe("Tomorrow (Wed)");      // the fixture's now: Tue
    expect(days.options[6].textContent).toBe("Tue");
    expect([...byTestId(view.host, "plan-slot").options].map((o) => o.textContent)).toEqual(["Morning, 10:00", "Afternoon, 14:00", "Evening, 19:00"]);
    expect(byTestId(view.host, "plan-venue").options[1].textContent).toBe("Drinks at The Anchor · The Quays");
    selectValue(byTestId(view.host, "plan-venue"), "the_anchor");
    selectValue(days, 3);
    selectValue(byTestId(view.host, "plan-slot"), "evening");
    click(button(view.host, "Ask Cole"));
    expect(act).toHaveBeenCalledWith({ action: "propose_meet", target: PID, args: { venue: "the_anchor", day: 3, slot: "evening" }, text: "" });
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

  it("Calendar: Go on the day, a confirm to call one off, past ones with their outcome", () => {
    const act = vi.fn();
    const due = { id: "t1", pid: PID, name: "Cole", venue: "the_anchor", venue_label: "The Anchor", when: "Tue 19:00", status: "due", start: 43, end: 45.5 };
    const done = { ...due, id: "t0", status: "done", recap_line: "It went well.", start: 20, end: 22 };
    view.render(<Calendar phone={phoneFixture({ phone: { calendar: [done, due] } })} act={act} />);
    click(button(byTestId(view.host, "meet-t1"), "Go"));
    expect(act).toHaveBeenCalledWith({ action: "meet", target: "t1", args: { do: "go" }, text: "" });
    expect(byTestId(view.host, "meet-t0").textContent).toContain("It went well.");
    expect(byText(view.host, "Coming up")).not.toBeNull();
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
    const meet = { id: "t1", pid: PID, name: "Cole", venue: "the_anchor", venue_label: "The Anchor", when: "Tue 19:00", status: "agreed", start: 43, end: 45.5 };
    const photo = { mid: "x4", kind: "photo", status: "fallback", url: "", poster_url: "", caption: "a view", pid: PID, name: "Cole",
      thread_id: `matchstick:${PID}`, message_id: "m9", at: 40.5 };
    const phone = plantHidden(phoneFixture({ phone: { calendar: [meet], gallery: [photo] } }), HIDDEN);
    view.render(<ContactCard contact={cole(phone)} phone={phone} act={vi.fn()} onBack={vi.fn()} onOpenThread={vi.fn()} />);
    expect(view.host.querySelector(".rr-story__row")).not.toBeNull();
    clean();
    click(button(view.host, "Plan a meet-up"));
    clean();
    view.render(<Contacts phone={phone} onOpenContact={vi.fn()} />);
    clean();
    view.render(<Photos phone={phone} onOpenThread={vi.fn()} />);
    click(view.host.querySelectorAll('[role="tab"]')[1]);
    expect(byTestId(view.host, "photo-x4")).not.toBeNull();
    clean();
    view.render(<Calendar phone={phone} act={vi.fn()} />);
    expect(byTestId(view.host, "meet-t1")).not.toBeNull();
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
    const meet = { id: "t1", pid: PID, name: "Cole", venue: "the_anchor", venue_label: "The Anchor", when: "Tue 19:00", status: "agreed", start: 60, end: 62.5 };
    view.render(<Harness onAct={vi.fn(() => true)} phone={phoneFixture({ phone: { calendar: [meet] } })} />);
    click(button(view.host, "Home"));
    click(byTestId(view.host, "app-calendar"));
    const entry = button(view.host, "With Cole");
    entry.focus();
    click(entry);
    click(button(view.host.querySelector(".rr-side"), "Close"));
    expect(document.activeElement).toBe(button(view.host, "With Cole"));
  });

  it("the Calendar's list holds only list items", () => {
    const meet = { id: "t1", pid: PID, name: "Cole", venue: "the_anchor", venue_label: "The Anchor", when: "Tue 19:00", status: "agreed", start: 60, end: 62.5 };
    view.render(<Calendar phone={phoneFixture({ phone: { calendar: [meet, { ...meet, id: "t0", status: "done", recap_line: "Fine." }] } })} act={vi.fn()} onOpenContact={vi.fn()} />);
    for (const list of view.host.querySelectorAll("ul")) {
      for (const child of list.children) expect(child.tagName).toBe("LI");
    }
  });
});

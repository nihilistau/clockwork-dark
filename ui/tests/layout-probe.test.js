// @vitest-environment jsdom
/**
 * The layout gate's probe (ui/tools/layout-probe.js), driven over stubbed
 * boxes -- jsdom has no layout -- plus the two CSS rules T6's review found
 * missing, pinned by text because only a browser can measure them
 * (ui/tools/layout-check.mjs does, at 390x844 and 844x390).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { probeHeader, probeLayout, probeStart, shelfHeadingVisible } from "../tools/layout-probe.js";

// The same root plugin-contract.test.js reads from: vitest runs in ui/.
const read = (path) => readFileSync(resolve(process.cwd(), "src", path), "utf8").replace(/\r\n/g, "\n");

/** Build a column from [selector-ish spec] and give every element a box. */
function column({ shelfOverflow = "auto", choicesBox, chipBox, panelBox, wrapperOverflow, buttonBox, shelfBox, toggleBox } = {}) {
  document.body.innerHTML = `
    <div id="grid">
      <section class="scene__col scene__col--main" style="overflow-y: auto">
        <div class="stage-area" style="overflow-y: ${wrapperOverflow || "visible"}">
          <div class="probe-stage"><button class="approach">Go</button></div>
        </div>
        <div class="log"></div>
        <div class="shelf" style="overflow-y: ${shelfOverflow}"><section class="casing"><button class="panel__toggle">Job</button></section></div>
        <div class="choices-area"><div class="choices"><button class="chip">Wait</button></div></div>
        <form class="compose"><input class="compose__input" /></form>
      </section>
    </div>`;
  const boxes = new Map([
    [".scene__col--main", [0, 600]],
    [".stage-area", [0, 100]],
    [".probe-stage", [0, 100]],
    [".approach", buttonBox || [40, 80]],
    [".log", [112, 300]],
    [".shelf", shelfBox || [312, 400]],
    [".casing", panelBox || [312, 400]],
    [".panel__toggle", toggleBox || [312, 356]],
    [".choices-area", choicesBox || [412, 456]],
    [".choices", choicesBox || [412, 456]],
    [".chip", chipBox || [412, 456]],
    [".compose", [468, 512]],
    [".compose__input", [468, 512]],
  ]);
  for (const [selector, [top, bottom]] of boxes) {
    const el = document.querySelector(selector);
    el.getBoundingClientRect = () => ({ top, bottom, left: 0, right: 800, width: 800, height: bottom - top });
  }
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("probeLayout", () => {
  it("a panel taller than its scrolling shelf does not count as an overlap", () => {
    column({ panelBox: [312, 700] });
    const result = probeLayout(true);
    expect(result.overlaps).toEqual([]);
    expect(result.overlapsRaw).toContain("casing");
    expect(result.failures).toEqual([]);
  });

  it("the same panel in a shelf that does not clip fails", () => {
    column({ panelBox: [312, 700], shelfOverflow: "visible" });
    const result = probeLayout(true);
    expect(result.overlaps).toContain("casing");
    expect(result.failures.join()).toMatch(/overlaps the choices/);
  });

  it("measures the chips, not the wrapper: a crushed wrapper's chips over the compose box fail", () => {
    column({ choicesBox: [468, 468], chipBox: [468, 512] });
    const result = probeLayout(true);
    expect(result.composeOverlaps).toContain("chip");
    expect(result.failures.join()).toMatch(/overlaps the compose box/);
  });

  it("an overlap below the column's fold still fails: the column scrolls, it does not hide", () => {
    column({ choicesBox: [468, 468], chipBox: [468, 512] });
    const col = document.querySelector(".scene__col--main");
    col.getBoundingClientRect = () => ({ top: 0, bottom: 400, left: 0, right: 800, width: 800, height: 400 });
    expect(probeLayout(false).composeOverlaps).toContain("chip");
  });

  it("a control cut by an ancestor that clips without scrolling is unreachable", () => {
    column({ wrapperOverflow: "hidden", buttonBox: [80, 140] });
    expect(probeLayout(true).clippedControls).toEqual(["approach: Go"]);
  });

  it("a control past a SCROLLING ancestor's edge is reachable", () => {
    column({ wrapperOverflow: "auto", buttonBox: [80, 140] });
    expect(probeLayout(true).clippedControls).toEqual([]);
  });

  it("a control inside a scroller crushed below its height is unreachable (T6 review issue B)", () => {
    // The shelf's track at 844x390 before its floor: 0px tall, so nothing in
    // it can be scrolled to, and the job panel's heading was simply gone.
    column({ shelfBox: [400, 400], panelBox: [400, 444], toggleBox: [400, 444] });
    expect(probeLayout(false).clippedControls).toEqual(["panel__toggle: Job"]);
  });

  it("a scroller at least as tall as the control keeps it reachable", () => {
    column({ shelfBox: [356, 400], panelBox: [356, 500], toggleBox: [356, 400] });
    expect(probeLayout(false).clippedControls).toEqual([]);
  });
});

/** A column whose shelf holds core's encounter panel; `row` draws a choice row. */
function encounterColumn({ approachBox, shelfBox = [312, 400], row = false, colBox = [0, 600] }) {
  document.body.innerHTML = `
    <div id="grid">
      <section class="scene__col scene__col--main" style="overflow-y: auto">
        <div class="log"></div>
        <div class="shelf" style="overflow-y: auto"><section class="encpanel">
          <button class="encpanel__approach" aria-disabled="true">Talk</button>
          <button class="encpanel__approach">Run</button>
        </section></div>
        <div class="choices-area">${row ? '<div class="choices"><button class="chip">Wait</button></div>' : ""}</div>
        <form class="compose"><input class="compose__input" /></form>
      </section>
    </div>`;
  const boxes = [
    [".scene__col--main", colBox],
    [".log", [0, 300]],
    [".shelf", shelfBox],
    [".encpanel", [shelfBox[0], 700]],
    [".encpanel__approach[aria-disabled]", [shelfBox[0] + 10, shelfBox[0] + 54]],
    [".encpanel__approach:not([aria-disabled])", approachBox],
    [".compose", [540, 584]],
    [".compose__input", [540, 584]],
    ...(row ? [[".choices", [420, 464]], [".chip", [420, 464]]] : []),
  ];
  for (const [selector, [top, bottom]] of boxes) {
    const el = document.querySelector(selector);
    el.getBoundingClientRect = () => ({ top, bottom, left: 0, right: 800, width: 800, height: bottom - top });
  }
}

describe("the encounter panel holding the only moves (T10 fix round 2)", () => {
  it("passes when its first pressable approach is on screen at rest", () => {
    encounterColumn({ approachBox: [340, 384] });
    const result = probeLayout(false);
    expect(result.firstApproachVisible).toBe(true);
    expect(result.failures).toEqual([]);
  });

  it("fails, at any size, when the approach sits below the shelf's fold", () => {
    // The 16vh shelf: heading and terms on screen, the buttons scrolled out.
    encounterColumn({ approachBox: [420, 464] });
    for (const strict of [true, false]) {
      const result = probeLayout(strict);
      expect(result.firstApproachVisible).toBe(false);
      expect(result.failures.join()).toMatch(/first approach is not fully on screen/);
    }
  });

  it("fails when the approach lies below the column's view", () => {
    encounterColumn({ approachBox: [560, 604], shelfBox: [312, 640], colBox: [0, 580] });
    expect(probeLayout(false).firstApproachVisible).toBe(false);
  });

  it("is not asked while a choice row still holds the digits", () => {
    encounterColumn({ approachBox: [420, 464], row: true });
    expect(probeLayout(false).firstApproachVisible).toBeNull();
  });
});

describe("the CSS the probe found missing (T6 review findings 1 and 2, issues B and C)", () => {
  it("the choice list keeps its one-chip floor under the area wrapper", () => {
    expect(read("styles/index.css")).toMatch(/\.choices-area:not\(:empty\)\s*\{\s*min-height:\s*44px;\s*\}/);
  });

  it("the choice list fills its area and shrinks with it (the flex half, T6 review issue C)", () => {
    const css = read("styles/index.css");
    expect(css).toMatch(/\.choices-area\s*\{[^}]*display:\s*flex;\s*flex-direction:\s*column;[^}]*\}/);
    expect(css).toMatch(/\.choices-area > \.choices\s*\{\s*flex:\s*1 1 auto;\s*\}/);
  });

  it("a shelf holding a panel keeps one heading row (T6 review issue B)", () => {
    expect(read("styles/index.css")).toMatch(/\.shelf:not\(:empty\)\s*\{\s*min-height:\s*44px;\s*\}/);
  });

  it("the flagship's narrow encounter gives the stage wrapper its natural height back", () => {
    const css = read("stories/clockwork-dark/theme/clockwork-dark.css");
    const narrow = css.slice(css.indexOf("@media (max-width: 560px), (max-height: 560px)"));
    expect(narrow).toMatch(
      /\.scene__col--main:has\(\.encounter\) > \.stage-area\s*\{\s*overflow:\s*visible;\s*min-height:\s*auto;\s*\}/
    );
    expect(narrow).toMatch(/\.scene__col--main \.stage-area > \.encounter\s*\{\s*min-height:\s*auto;\s*\}/);
  });
});

// ---------------------------------------------------------------------------
// The top bar (T8 review findings 2 and 3)
// ---------------------------------------------------------------------------

/** A header whose elements each have a stubbed box: [left, right, top, bottom]. */
function header({ ring = [300, 309, 20, 29], title = [20, 120, 20, 40], chip = [140, 260, 8, 52], clock = [321, 380, 20, 40], width = 390 } = {}) {
  document.body.innerHTML = `
    <header class="chrome chrome--top">
      <div class="chrome__left"><h1 class="chrome__title">The Lantern House</h1></div>
      <div class="chrome__right">
        <button class="wanted-chip">wanted</button>
        <span class="chrome__clock"><span class="ring"></span><span class="clock">Day 1</span></span>
      </div>
    </header>`;
  const at = (selector, [left, right, top, bottom]) => {
    const el = document.querySelector(selector);
    el.getBoundingClientRect = () => ({ left, right, top, bottom, width: right - left, height: bottom - top });
    return el;
  };
  const head = at(".chrome--top", [0, width, 0, 60]);
  Object.defineProperty(head, "scrollWidth", { configurable: true, value: width });
  Object.defineProperty(head, "clientWidth", { configurable: true, value: width });
  at(".chrome__title", title);
  at(".wanted-chip", chip);
  at(".clock", clock);
  at(".ring", ring);
  at(".chrome__right", [140, width, 0, 60]);
  at(".chrome__clock", [300, 380, 20, 40]);
  at(".chrome__left", [0, 130, 0, 60]);
}

describe("probeHeader", () => {
  it("a round ring, a chip clear of the name and the clock, nothing past the edge: no failure", () => {
    header();
    const result = probeHeader();
    expect(result.failures).toEqual([]);
    expect(result.gap).toBe(20);
  });

  it("a ring collapsed to a bar fails (the regression this fix closes)", () => {
    header({ ring: [321, 323, 20, 40] });
    expect(probeHeader().failures.join()).toMatch(/ring is not round/);
  });

  it("a ring butted against the day fails", () => {
    header({ ring: [312, 321, 20, 29] });
    expect(probeHeader().failures.join()).toMatch(/ring touches the day/);
  });

  it("a chip that runs over the clock fails", () => {
    header({ chip: [140, 330, 8, 52] });
    expect(probeHeader().failures.join()).toMatch(/chip overlaps the clock/);
  });

  it("content past the header's right edge fails", () => {
    header({ clock: [321, 420, 20, 40] });
    expect(probeHeader().failures.join()).toMatch(/outside the header/);
  });

  it("a place name that wraps onto a second line fails", () => {
    header();
    const title = document.querySelector(".chrome__title");
    const real = document.createRange;
    document.createRange = () => ({
      selectNodeContents() {},
      getClientRects: () => [{ top: 20, width: 80 }, { top: 36, width: 60 }],
    });
    try {
      expect(probeHeader().failures.join()).toMatch(/place name wraps/);
    } finally {
      document.createRange = real;
    }
    expect(title).toBeTruthy();
  });

  it("a page with no header reports nothing", () => {
    document.body.innerHTML = "";
    expect(probeHeader()).toEqual({ failures: [], present: false });
  });
});

describe("the header's CSS", () => {
  const css = read("styles/index.css");

  it("the clock group is a flex row, so the ring keeps its box", () => {
    expect(css).toMatch(/\.chrome__clock\s*\{[^}]*display:\s*inline-flex[^}]*align-items:\s*center[^}]*gap:/);
  });

  it("the chip never wraps, the place name gives way with an ellipsis, and a narrow chip is only its band", () => {
    expect(css).toMatch(/\.wanted-chip\s*\{[^}]*white-space:\s*nowrap/);
    expect(css).toMatch(/\.chrome--top \.chrome__title\s*\{[^}]*text-overflow:\s*ellipsis/);
    expect(css).toMatch(/@media \(max-width: 560px\)\s*\{[^}]*\.chip__rest,\s*\.chip__where\s*\{\s*display:\s*none/);
  });
});

/** A roll card in the column's toast area, with a stubbed box. */
function toast([top, bottom], [left, right] = [600, 790]) {
  const area = document.createElement("div");
  area.className = "toast-area";
  area.innerHTML = '<div class="rollcard-live"><div class="rollcard">stealth</div></div>';
  document.querySelector(".scene__col--main").appendChild(area);
  const card = area.querySelector(".rollcard");
  card.getBoundingClientRect = () => ({ top, bottom, left, right, width: right - left, height: bottom - top });
  for (const el of [area, area.firstChild]) {
    el.getBoundingClientRect = () => ({ top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 });
  }
}

describe("the roll card in probeLayout (T9 review finding 1)", () => {
  it("a card over the stage and log passes", () => {
    column();
    toast([8, 140]);
    const result = probeLayout(true);
    expect(result.toastOverlaps).toEqual([]);
    expect(result.toastShown).toBe(1);
    expect(result.failures).toEqual([]);
  });

  it("a card on a chip or the compose box fails, whatever clips it", () => {
    column();
    toast([400, 520]);
    const result = probeLayout(false);
    expect(result.toastOverlaps).toEqual(expect.arrayContaining(["chip", "compose"]));
    expect(result.failures.join()).toMatch(/roll card overlaps/);
  });

  it("a card outside the main column (over the ledger) fails", () => {
    column();
    toast([8, 140], [810, 1000]);
    expect(probeLayout(true).failures.join()).toMatch(/outside the main column/);
  });
});

describe("shelfHeadingVisible (T9 review finding 9)", () => {
  const heading = (headingBox, shelfBox) => {
    column({ shelfBox });
    const h = document.createElement("h2");
    h.id = "panel-job-title";
    document.querySelector(".shelf .casing").prepend(h);
    const [top, bottom] = headingBox;
    h.getBoundingClientRect = () => ({ top, bottom, left: 0, right: 800, width: 800, height: bottom - top });
  };

  it("a heading inside its shelf and the column's view is on screen", () => {
    heading([312, 356], [312, 400]);
    expect(shelfHeadingVisible("panel-job-title")).toBe(true);
  });

  it("a shelf crushed to 0px shows nothing, though the heading has a box", () => {
    heading([312, 356], [312, 312]);
    expect(shelfHeadingVisible("panel-job-title")).toBe(false);
  });

  it("a heading below the column's fold is not on screen", () => {
    heading([590, 634], [590, 700]);
    expect(shelfHeadingVisible("panel-job-title")).toBe(false);
  });

  it("an unknown heading is not on screen", () => {
    column();
    expect(shelfHeadingVisible("panel-nothing-title")).toBe(false);
  });
});

describe("final fix wave: the log's floor, the empty aside, the tab bar (findings 18-20)", () => {
  it("logFloor fails a log under the column's --log-min, and passes one that holds it", () => {
    const real = HTMLElement.prototype.getBoundingClientRect;
    const floorAt = (px) => {
      HTMLElement.prototype.getBoundingClientRect = function stub() {
        if (this.style && this.style.cssText.includes("--log-min")) return { top: 0, bottom: px, left: 0, right: 1, width: 1, height: px };
        return real.call(this);
      };
    };
    try {
      column(); // the log is 188px tall (112..300)
      floorAt(250);
      const under = probeLayout(true);
      expect(under.logFloor.ok).toBe(false);
      expect(under.failures.join()).toMatch(/the log is under its floor/);
      column();
      floorAt(150);
      expect(probeLayout(true).logFloor.ok).toBe(true);
    } finally {
      HTMLElement.prototype.getBoundingClientRect = real;
    }
  });

  it("advises (never fails) on a log shorter than the shelf", () => {
    column({ shelfBox: [312, 600], panelBox: [312, 600] });
    const result = probeLayout(false);
    expect(result.advisories.join()).toMatch(/logStarved/);
    expect(result.failures.join()).not.toMatch(/logStarved/);
  });

  const css = read("styles/index.css");

  it("an asideless scene drops the assistant track on desktop only", () => {
    expect(css).toMatch(
      /@media \(min-width: 901px\) \{\s*\.scene\[data-aside="off"\] \.scene__grid \{\s*grid-template-columns: minmax\(0, 1fr\) var\(--col-sheet\);/
    );
    expect(css).toMatch(/\.scene\[data-aside="off"\] \.scene__col--assistant \{\s*display: none;/);
  });

  it("the tab bar paints above the scene's atmosphere", () => {
    expect(css).toMatch(/\.tabbar \{\s*display: none;[\s\S]*?position: relative;\s*z-index: 1;/);
  });

  it("a short window holds the log to three lines and caps the shelf beside the strip", () => {
    expect(css).toMatch(/@media \(max-height: 819\.98px\) \{\s*\.scene__col--main \{\s*--log-min: 8rem;/);
    expect(css).toMatch(/\.scene__col--main:has\(> \.stage-area > \.people\) \{\s*--shelf-max: 20vh;/);
  });
});

/** Stub every element's box from a selector map (jsdom has no layout). */
function stubBoxes(map) {
  for (const [selector, [left, top, right, bottom]] of map) {
    for (const el of document.querySelectorAll(selector)) {
      el.getBoundingClientRect = () => ({ top, bottom, left, right, width: right - left, height: bottom - top });
    }
  }
}

describe("the start screen's overflow (v0.21.0, the archetypes past the card)", () => {
  const screen = (fieldsetRight) => {
    document.body.innerHTML = `
      <div class="start"><form class="start__card">
        <fieldset class="archetypes"><label class="archetype"><span class="archetype__blurb">A long line</span></label></fieldset>
        <button type="submit">Begin</button>
      </form></div>`;
    stubBoxes(new Map([
      // jsdom's window is 1024px wide.
      [".start", [0, 0, 1024, 768]],
      [".start__card", [232, 12, 792, 700]],
      [".archetypes", [253, 300, fieldsetRight, 400]],
      [".archetype", [253, 300, fieldsetRight, 360]],
      [".archetype__blurb", [266, 320, fieldsetRight - 13, 340]],
      ["button", [253, 600, 771, 650]],
    ]));
  };

  it("an archetype inside the card passes", () => {
    screen(771);
    expect(probeStart().failures).toEqual([]);
  });

  it("an archetype past the card's side fails, and past the window's", () => {
    screen(988);
    expect(probeStart().failures.join()).toMatch(/runs past its edge: archetypes/);
    screen(1412);
    expect(probeStart().overflowing.join()).toMatch(/of 1024/);
  });

  it("the fold is asked only when the gate asks for it", () => {
    screen(771);
    document.querySelector("button").getBoundingClientRect = () => ({ top: 800, bottom: 850, left: 253, right: 771, width: 518, height: 50 });
    expect(probeStart({ fold: true }).failures.join()).toMatch(/below the fold/);
    expect(probeStart({ fold: false }).failures).toEqual([]);
  });

  it("the CSS: the fieldset may shrink to the card, and a short window no longer forces one line", () => {
    const css = read("styles/index.css");
    expect(css).toMatch(/\.archetypes \{\s*min-inline-size: 0;/);
    expect(css).not.toMatch(/\.archetype__blurb \{\s*white-space: nowrap;/);
  });
});

describe("the people strip and the log's lines on a phone (v0.21.0)", () => {
  const strip = (rights, overflowX = "auto") => {
    column();
    const stage = document.querySelector(".stage-area");
    stage.insertAdjacentHTML(
      "beforeend",
      `<section class="people people--stage"><ul class="people__list" style="overflow-x: ${overflowX}">${rights
        .map((_, i) => `<li class="people__card c${i}">P${i}</li>`)
        .join("")}</ul></section>`
    );
    const map = new Map([[".people", [12, 50, 378, 100]], [".people__list", [12, 50, 378, 100]]]);
    let left = 12;
    rights.forEach((right, i) => {
      map.set(`.c${i}`, [left, 50, right, 100]);
      left = right + 8;
    });
    stubBoxes(map);
  };

  it("two whole cards and two scrolled wholly out of view pass", () => {
    strip([191, 378, 565, 752]);
    expect(probeLayout(true).people.cut).toEqual([]);
  });

  it("a card cut at the strip's edge fails (the 390x844 capture)", () => {
    strip([172, 340, 508, 676]);
    const result = probeLayout(true);
    expect(result.people.cut).toEqual(["P2"]);
    expect(result.failures.join()).toMatch(/the people strip cuts a card/);
  });

  it("a strip that does not scroll sideways cannot hide a card past the window", () => {
    strip([191, 378, 1100], "visible"); // jsdom's window is 1024px wide
    expect(probeLayout(true).people.cut).toEqual(["P2"]);
  });

  it("logLines: a first line cut over three whole lines fails; four whole lines scrolling pass", () => {
    const realRange = document.createRange;
    const lineAt = (tops) => {
      document.createRange = () => {
        const range = realRange.call(document);
        range.getClientRects = () => tops.map((top) => ({ top, bottom: top + 22, left: 30, right: 300, width: 270, height: 22 }));
        return range;
      };
    };
    try {
      column(); // the log is 112..300
      const log = document.querySelector(".log");
      log.innerHTML = "<p>narration</p>";
      Object.defineProperty(log, "clientHeight", { value: 188 });
      lineAt([100, 122, 144, 166]);
      // One text node, so one call: give it every line at once.
      let result = probeLayout(true);
      expect(result.logLines).toMatchObject({ whole: 3, cutTop: 1 });
      expect(result.failures.join()).toMatch(/first visible line is cut at its top/);
      lineAt([100, 122, 144, 166, 188]);
      result = probeLayout(true);
      expect(result.logLines).toMatchObject({ whole: 4, cutTop: 1 });
      expect(result.failures.join()).not.toMatch(/log/);
      lineAt([120, 142]);
      expect(probeLayout(true).failures.join()).not.toMatch(/log/);
    } finally {
      document.createRange = realRange;
    }
  });

  it("the CSS: a narrow column turns the split over and the strip snaps whole cards", () => {
    const css = read("styles/index.css");
    expect(css).toMatch(/@media \(max-width: 600px\) \{\s*\.scene__col--main:has\(> \.stage-area > \.people\) \{\s*--row-visual: 4fr;\s*--row-log: 6fr;/);
    expect(css).toMatch(/\.people--stage \.people__list \{ scroll-snap-type: x mandatory; \}/);
    expect(css).toMatch(/flex: 0 0 calc\(\(100% - var\(--space-2\)\) \/ 2\)/);
  });
});

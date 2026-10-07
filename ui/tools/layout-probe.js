/**
 * The play screen's layout probe (v0.21.0, spec §3.4; T6 review finding 3).
 *
 * One function, run INSIDE the page (`page.evaluate(probeLayout)`), so it
 * must stay self-contained: no import, no closure over this module. It is
 * also imported by `ui/tests/layout-probe.test.js`, which drives it over
 * stubbed boxes, and by `ui/tools/layout-check.mjs`, the gate T7 and the
 * release run.
 *
 * WHY A CLIPPED CHECK. A panel taller than the capped shelf has a raw
 * `getBoundingClientRect` box that runs past the shelf's edge -- over the
 * choices -- while painting nothing there, because the shelf scrolls. So
 * every box is first CLIPPED by each ancestor INSIDE the column whose
 * `overflow-y` is not `visible`, and only the clipped boxes are compared. The
 * column itself is not a clip: it scrolls, so an overlap below its fold is
 * one scroll away (on a landscape phone the floors outgrow it, and a list
 * overflowing its crushed track hid under the fold over the compose box). The raw result is kept as information only.
 *
 * WHAT IS GATED (`failures`):
 *   - `overlaps`: an element of the column, at any depth, whose clipped box
 *     intersects a choice chip's (the CHIPS, not the `.choices-area`
 *     wrapper: a wrapper crushed to 0px passes any wrapper test vacuously);
 *   - `composeOverlaps`: the same against the compose box;
 *   - `clippedControls`: a control (button, link, input) cut by an ancestor
 *     that clips WITHOUT scrolling (`hidden`, `clip`), or inside a scroller
 *     shorter than itself (a shelf crushed to 0px scrolls to nothing): it
 *     cannot be reached;
 *   - `pageScrolls`: the page itself scrolls;
 *   - `toastOverlaps`: a roll card (`.rollcard`) whose raw box meets a chip
 *     or the compose box, or that lies outside the main column (T9);
 *   - when `strict` (the spec's three sizes, and no encounter owning the
 *     stage): the compose box and the first chip are fully on screen;
 *   - `firstApproachVisible`, at EVERY size (T10 fix round 2): when core's
 *     encounter panel holds the only moves (an `.encpanel` in the shelf and
 *     no choice row), its first pressable approach is fully on screen in the
 *     column's view at rest -- before, under 900px, they sat below the
 *     shelf's 16vh fold, the heading the only thing showing;
 *   - `logFloor` (final review finding 19): the log box plus its margin is
 *     at least the column's computed `--log-min`;
 *   - `logLines` (v0.21.0, the phone capture): at least three whole lines of
 *     narration in view (or all of them, if fewer), and no first line cut at
 *     the log's top over three whole lines or fewer;
 *   - `people`: the stage's people strip lies inside the window and cuts no
 *     card at its edge (a card wholly scrolled out of a sideways scroller is
 *     allowed).
 * ADVISORIES (`advisories`, printed, never failed): `logStarved` (the log is
 * shorter than the shelf) and `choicesHidden` (the choice list scrolls).
 * NOT SEEN: a pseudo-element painted over a control (`.scene::before` over
 * the tab bar, finding 20) -- `elementFromPoint` never returns one.
 * `paintedOver` (what `elementFromPoint` finds at each chip's and the compose
 * box's centre) is a secondary report: it skips `pointer-events: none`
 * layers and sees only on-screen points, so it cannot be the gate.
 */
export function probeLayout(strict = true) {
  const col = document.querySelector(".scene__col--main");
  if (!col) return { failures: ["no .scene__col--main on the page"] };
  const stop = col.parentElement;
  const box = (el) => {
    const b = el.getBoundingClientRect();
    return { top: b.top, bottom: b.bottom, left: b.left, right: b.right };
  };
  // Clipped by the scrollers INSIDE the column, not by the column itself:
  // the column scrolls, so whatever lies past its edge is one scroll away
  // and must not overlap anything there either.
  const clipped = (el) => {
    const b = box(el);
    for (let p = el.parentElement; p && p !== col; p = p.parentElement) {
      if (getComputedStyle(p).overflowY === "visible") continue;
      const a = box(p);
      b.top = Math.max(b.top, a.top);
      b.bottom = Math.min(b.bottom, a.bottom);
      b.left = Math.max(b.left, a.left);
      b.right = Math.min(b.right, a.right);
    }
    return b;
  };
  const area = (b) => Math.max(0, b.bottom - b.top) * Math.max(0, b.right - b.left);
  const meets = (a, b) =>
    a.bottom > b.top + 0.5 && a.top < b.bottom - 0.5 && a.right > b.left + 0.5 && a.left < b.right - 0.5;
  const name = (el) =>
    (typeof el.className === "string" && el.className.trim()) || el.tagName.toLowerCase();
  const shown = (el) => {
    const s = getComputedStyle(el);
    return s.visibility !== "hidden" && s.display !== "contents" && !el.classList.contains("visually-hidden");
  };

  const chips = [...col.querySelectorAll(".choices .chip, .choices__empty")];
  const compose = col.querySelector(".compose");
  const all = [...col.querySelectorAll("*")].filter(shown);

  // Everything that is not the target, inside it, or holding it.
  const against = (targets, raw) => {
    const hits = new Set();
    for (const target of targets) {
      const t = raw ? box(target) : clipped(target);
      if (area(t) <= 0) continue;
      for (const el of all) {
        if (el === target || target.contains(el) || el.contains(target)) continue;
        if (targets.some((other) => other.contains(el) || el.contains(other))) continue;
        const b = raw ? box(el) : clipped(el);
        if (area(b) < 1) continue;
        if (meets(b, t)) hits.add(name(el));
      }
    }
    return [...hits];
  };

  // A chip's own list is not an intruder on a chip.
  const list = col.querySelector(".choices");
  const chipTargets = chips;
  const notTheList = (hits) => hits.filter((n) => n !== "choices" && n !== "choices-area");
  const overlaps = notTheList(against(chipTargets, false));
  const overlapsRaw = notTheList(against(chipTargets, true));
  const composeOverlaps = compose ? against([compose], false) : [];

  const clippedControls = [];
  for (const el of col.querySelectorAll("button, a[href], input, select, textarea")) {
    if (!shown(el)) continue;
    const b = box(el);
    if (area(b) <= 0) continue;
    for (let p = el.parentElement; p && p !== stop; p = p.parentElement) {
      const o = getComputedStyle(p).overflowY;
      if (o === "visible") continue;
      const a = box(p);
      // A clip that does not scroll cuts whatever lies past its edge. A
      // scroller does not -- unless it is SHORTER than the control: a shelf
      // crushed to 0px cannot be scrolled to anything (T6 review issue B).
      const cut =
        o === "hidden" || o === "clip"
          ? b.top < a.top - 0.5 || b.bottom > a.bottom + 0.5
          : a.bottom - a.top < b.bottom - b.top - 0.5;
      if (cut) {
        clippedControls.push(`${name(el)}: ${(el.textContent || "").trim().slice(0, 40)}`);
        break;
      }
    }
  }

  const paintedOver = new Set();
  for (const el of [...chips, ...(compose ? [compose] : [])]) {
    const b = clipped(el);
    if (area(b) <= 0) continue;
    const x = (b.left + b.right) / 2;
    const y = (b.top + b.bottom) / 2;
    const hit = document.elementFromPoint ? document.elementFromPoint(x, y) : null;
    if (hit && !el.contains(hit) && !hit.contains(el)) paintedOver.add(name(hit));
  }

  const onScreen = (el) => {
    if (!el) return true;
    const b = box(el);
    const c = clipped(el);
    const v = box(col); // in the column's scrolled view, not under the tab bar
    return (
      b.top >= Math.max(0, v.top) - 0.5 &&
      b.bottom <= Math.min(innerHeight, v.bottom) + 0.5 &&
      c.bottom - c.top >= b.bottom - b.top - 0.5
    );
  };
  const encounter = Boolean(col.querySelector(".encounter"));
  // Core's encounter panel holding the only moves: no choice row is drawn.
  const choiceRow = col.querySelector(".choices-area > *");
  const approaches = [...col.querySelectorAll(".shelf .encpanel__approach")];
  const holdsMoves = approaches.length > 0 && !choiceRow;
  const firstApproach = approaches.find((el) => el.getAttribute("aria-disabled") !== "true") || null;
  const firstApproachVisible = holdsMoves ? Boolean(firstApproach) && onScreen(firstApproach) : null;
  const composeVisible = onScreen(compose);
  const firstChipVisible = onScreen(chips[0]);
  const pageScrolls = document.scrollingElement
    ? document.scrollingElement.scrollHeight > innerHeight
    : false;

  const heights = {};
  for (const el of col.children) {
    if (el.classList.contains("visually-hidden")) continue;
    heights[el.classList[0] || el.tagName.toLowerCase()] = Math.round((box(el).bottom - box(el).top) * 10) / 10;
  }

  // The toast (the roll card, T9 review finding 1): its RAW box -- a toast
  // is drawn wherever its own positioning puts it, so no ancestor's clip is
  // trusted -- must meet no chip and not the compose box, and must sit
  // inside the main column, not over the ledger.
  const colBox = box(col);
  const toastOverlaps = [];
  const toastOutside = [];
  for (const toast of document.querySelectorAll(".rollcard")) {
    const t = box(toast);
    if (area(t) <= 0) continue;
    for (const target of [...chips, ...(compose ? [compose] : [])]) {
      if (meets(t, box(target))) toastOverlaps.push(name(target));
    }
    if (t.left < colBox.left - 0.5 || t.right > colBox.right + 0.5) toastOutside.push(name(toast));
  }

  // THE LOG'S FLOOR (v0.21.0 final review finding 19). A structural guard:
  // the log box plus its top margin must hold the column's computed
  // `--log-min` -- a theme that overrides the rows (the flagship does, twice)
  // must keep the floor. Measured only while the main column is shown.
  const logEl = col.querySelector(":scope > .log");
  let logFloor = null;
  if (logEl && getComputedStyle(col).display !== "none") {
    const probeEl = document.createElement("div");
    probeEl.style.cssText = "position:absolute;visibility:hidden;height:var(--log-min)";
    col.appendChild(probeEl);
    const floor = probeEl.getBoundingClientRect().height;
    probeEl.remove();
    const margin = parseFloat(getComputedStyle(logEl).marginTop) || 0;
    const height = logEl.getBoundingClientRect().height;
    logFloor = { floor: Math.round(floor), log: Math.round(height), margin: Math.round(margin), ok: height + margin >= floor - 1 };
  }
  // ADVISORIES at desktop sizes, printed and never failed: the log shorter
  // than the shelf, and choices hidden below the list's own fold.
  const advisories = [];
  const shelfEl = col.querySelector(":scope > .shelf");
  if (logEl && shelfEl && logEl.getBoundingClientRect().height < shelfEl.getBoundingClientRect().height - 0.5) {
    advisories.push("logStarved: the log is shorter than the shelf");
  }
  if (list && list.scrollHeight - list.clientHeight > 0.5) advisories.push("choicesHidden: the choice list scrolls");

  // THE LOG'S LINES (v0.21.0, the README's phone capture). The floor above
  // is the track's; this is what a player reads in it. Every line box of the
  // log's text, measured against the log's visible (padding) box as it sits,
  // scrolled to the newest entry: `whole` lines lie inside it, `cutTop` lines
  // straddle its top edge. GATED: fewer than three whole lines (or fewer than
  // the log holds, if it holds fewer), and a first line cut at the top over
  // three whole lines or fewer -- the squeezed box at 390x844, where the
  // stage took 6fr of the room and the log showed a sliver and three lines.
  // A log with four whole lines in view may scroll its oldest line off the
  // top; that is scrolling. Null where the page has no layout (jsdom).
  let logLines = null;
  if (logEl && getComputedStyle(col).display !== "none" && document.createRange && document.createTreeWalker) {
    const probeRange = document.createRange();
    if (typeof probeRange.getClientRects === "function") {
      const lb = logEl.getBoundingClientRect();
      const top = lb.top + (logEl.clientTop || 0);
      const bottom = top + logEl.clientHeight;
      const rows = new Map();
      const walker = document.createTreeWalker(logEl, 4 /* NodeFilter.SHOW_TEXT */);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (!node.textContent.trim()) continue;
        const range = document.createRange();
        range.selectNodeContents(node);
        for (const r of range.getClientRects()) {
          if (r.width < 1 || r.height < 1) continue;
          const key = Math.round(r.top);
          if (!rows.has(key)) rows.set(key, { top: r.top, bottom: r.bottom });
        }
      }
      const lines = [...rows.values()];
      const whole = lines.filter((l) => l.top >= top - 0.5 && l.bottom <= bottom + 0.5).length;
      const cutTop = lines.filter((l) => l.top < top - 0.5 && l.bottom > top + 0.5).length;
      logLines = { lines: lines.length, whole, cutTop, view: Math.round(bottom - top) };
    }
  }

  // THE PEOPLE STRIP IN THE STAGE (v0.21.0, the README's phone capture): it
  // must lie inside the window, and no card of it may be CUT -- partly in
  // view and partly past the strip's own scrolling edge or the window's. A
  // card wholly scrolled out of view is a swipe away, which is allowed; a
  // list that does not scroll sideways cannot hide one at all.
  let people = null;
  const strip = document.querySelector(".stage-area > .people");
  if (strip && getComputedStyle(col).display !== "none") {
    const sb = box(strip);
    const stripList = strip.querySelector(".people__list") || strip;
    const ox = getComputedStyle(stripList).overflowX;
    const scrolls = ox === "auto" || ox === "scroll";
    const lb2 = box(stripList);
    const viewLeft = Math.max(0, scrolls ? lb2.left : -Infinity);
    const viewRight = Math.min(innerWidth, scrolls ? lb2.right : Infinity);
    const cut = [];
    for (const card of stripList.children) {
      if (card.classList.contains("visually-hidden")) continue;
      const b = box(card);
      const width = b.right - b.left;
      if (width <= 0) continue;
      const seen = Math.min(b.right, viewRight) - Math.max(b.left, viewLeft);
      const hidden = seen <= 0.5;
      if (!(hidden && scrolls) && seen < width - 0.5) cut.push((card.textContent || "").trim().slice(0, 24) || name(card));
    }
    people = {
      left: Math.round(sb.left),
      right: Math.round(sb.right),
      scrolls,
      cut,
      outside: sb.left < -0.5 || sb.right > innerWidth + 0.5,
    };
  }

  const failures = [];
  if (logLines && logLines.whole < Math.min(3, logLines.lines)) {
    failures.push(`the log shows ${logLines.whole} whole line(s) of ${logLines.lines}`);
  }
  if (logLines && logLines.cutTop && logLines.whole <= 3) {
    failures.push(`the log's first visible line is cut at its top, over ${logLines.whole} whole line(s)`);
  }
  if (people && people.outside) failures.push(`the people strip runs past the window (${people.left}..${people.right} of ${innerWidth})`);
  if (people && people.cut.length) failures.push(`the people strip cuts a card: ${people.cut.join("; ")}`);
  if (logFloor && !logFloor.ok) failures.push(`the log is under its floor (${logFloor.log}px + ${logFloor.margin}px margin < ${logFloor.floor}px)`);
  if (toastOverlaps.length) failures.push(`the roll card overlaps: ${toastOverlaps.join(", ")}`);
  if (toastOutside.length) failures.push("the roll card is outside the main column");
  if (overlaps.length) failures.push(`something overlaps the choices: ${overlaps.join(", ")}`);
  if (composeOverlaps.length) failures.push(`something overlaps the compose box: ${composeOverlaps.join(", ")}`);
  if (clippedControls.length) failures.push(`controls cut off unreachably: ${clippedControls.join("; ")}`);
  if (pageScrolls) failures.push("the page scrolls");
  if (firstApproachVisible === false) failures.push("the first approach is not fully on screen while it holds the only moves");
  if (strict && !encounter) {
    if (!composeVisible) failures.push("the compose box is not fully on screen");
    if (!firstChipVisible) failures.push("the first chip is not fully on screen");
  }

  return {
    failures,
    advisories,
    logFloor,
    logLines,
    people,
    overlaps,
    composeOverlaps,
    clippedControls,
    pageScrolls,
    composeVisible,
    firstChipVisible,
    firstApproachVisible,
    firstApproach: firstApproach ? box(firstApproach) : null,
    paintedOver: [...paintedOver],
    overlapsRaw,
    toastOverlaps,
    toastShown: document.querySelectorAll(".rollcard").length,
    encounter,
    stage: col.dataset.stage || "",
    rows: getComputedStyle(col).gridTemplateRows,
    heights,
    columnHeight: Math.round((box(col).bottom - box(col).top) * 10) / 10,
    columnScroll: col.scrollHeight - col.clientHeight,
    chips: chips.length,
    choicesScroll: list ? list.scrollHeight - list.clientHeight : null,
  };
}

/**
 * The top bar's probe (v0.21.0 T8 fix round 1; T8 review findings 2 and 3).
 * Self-contained, like `probeLayout`: it runs in the page, and the vitest
 * drives it over stubbed boxes.
 *
 * GATED (`failures`): the header scrolls sideways; any element in it paints
 * past the header's own box; the place name, the chip or the clock wraps onto
 * a second line; the ring is not round (|w - h| > 1, or under 4px: a bar, as
 * it was before this fix) or sits within 4px of the day; the place name, the
 * chip and the clock overlap one another.
 *
 * INFORMATION: `gap` (the space between the place name's right edge and the
 * first thing on the right, which is the header's slack), `titleClipped` (the
 * name is ellipsized: allowed, the chip and the clock never give way to it),
 * and the chip's text as shown.
 */
export function probeHeader() {
  const head = document.querySelector(".chrome--top");
  if (!head) return { failures: [], present: false };
  const rect = (el) => el.getBoundingClientRect();
  const hb = rect(head);
  const title = head.querySelector(".chrome__title");
  const chip = head.querySelector(".wanted-chip");
  const clock = head.querySelector(".clock");
  const ring = head.querySelector(".ring");
  const right = head.querySelector(".chrome__right");
  const lines = (el) => {
    if (!el || !document.createRange) return 1;
    const range = document.createRange();
    if (typeof range.getClientRects !== "function") return 1; // jsdom has no layout
    range.selectNodeContents(el);
    const tops = new Set([...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.top)));
    return Math.max(1, tops.size);
  };
  const meets = (a, b) => a.right > b.left + 0.5 && a.left < b.right - 0.5 && a.bottom > b.top + 0.5 && a.top < b.bottom - 0.5;
  const name = (el) => (typeof el.className === "string" && el.className.trim()) || el.tagName.toLowerCase();

  const failures = [];
  if (head.scrollWidth > head.clientWidth + 0.5) failures.push("the header scrolls sideways");
  const past = [];
  for (const el of head.querySelectorAll("*")) {
    const b = rect(el);
    if (b.width <= 0 || b.height <= 0) continue;
    if (b.right > hb.right + 0.5 || b.left < hb.left - 0.5) past.push(name(el));
  }
  if (past.length) failures.push(`header content outside the header: ${[...new Set(past)].join(", ")}`);
  for (const [label, el] of [["place name", title], ["chip", chip], ["clock", clock]]) {
    if (el && lines(el) > 1) failures.push(`the ${label} wraps onto a second line`);
  }
  if (ring) {
    const r = rect(ring);
    if (Math.abs(r.width - r.height) > 1 || r.width < 4) {
      failures.push(`the ring is not round (${Math.round(r.width)}x${Math.round(r.height)})`);
    }
    if (clock && rect(clock).left - r.right < 4) failures.push("the ring touches the day");
  }
  // The place name, the chip, the clock AND whatever else sits on the right (a
  // story's header badge) must not overlap one another.
  const boxes = [["place name", title], ["chip", chip], ["clock", clock]].filter(([, el]) => el);
  for (const el of right ? right.children : []) {
    if (el === chip || el === clock || el.contains(clock) || el.contains(chip)) continue;
    boxes.push([name(el), el]);
  }
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      if (meets(rect(boxes[i][1]), rect(boxes[j][1]))) failures.push(`the ${boxes[i][0]} overlaps the ${boxes[j][0]}`);
    }
  }
  const first = right ? right.firstElementChild : null;
  return {
    failures,
    present: true,
    gap: title && first ? Math.round((rect(first).left - rect(title).right) * 10) / 10 : null,
    titleClipped: title ? title.scrollWidth > title.clientWidth + 0.5 : false,
    title: title ? title.textContent : "",
    chip: chip ? chip.innerText || chip.textContent : null,
    headerWidth: Math.round(hb.width),
  };
}

/**
 * Whether a shelf panel's heading is ON SCREEN (v0.21.0 T9; T6 review issue
 * B): inside its shelf's box (a shelf crushed to 0px shows nothing) and
 * inside the main column's view of the window (the footer and the tab bar
 * sit over the window's bottom edge). Self-contained: it runs in the page
 * (`layout-check.mjs`'s shelf gate) and under the vitest over stubbed boxes.
 */
export function shelfHeadingVisible(headingId) {
  const h = document.getElementById(headingId);
  const shelf = h && h.closest(".shelf");
  if (!h || !shelf) return false;
  const b = h.getBoundingClientRect();
  const s = shelf.getBoundingClientRect();
  const col = shelf.closest(".scene__col--main");
  const v = col ? col.getBoundingClientRect() : { top: 0, bottom: innerHeight };
  return (
    b.height > 0 && b.width > 0 &&
    b.top >= Math.max(0, v.top) - 0.5 && b.bottom <= Math.min(innerHeight, v.bottom) + 0.5 &&
    b.top >= s.top - 0.5 && b.bottom <= s.bottom + 0.5
  );
}

/**
 * Controls cut off unreachably inside one column (v0.21.0 final review
 * finding 23): the same walk as `probeLayout`'s `clippedControls`, over any
 * column -- the ledger's `.scene__col--sheet` while it is shown. A clip that
 * does not scroll cuts what lies past it; a scroller shorter than the
 * control cannot be scrolled to it. Self-contained: it runs in the page.
 */
export function clippedControlsIn(selector) {
  const root = document.querySelector(selector);
  if (!root) return [];
  const box = (el) => el.getBoundingClientRect();
  const stop = root.parentElement;
  const out = [];
  for (const el of root.querySelectorAll("button, a[href], input, select, textarea")) {
    const st = getComputedStyle(el);
    if (st.visibility === "hidden" || st.display === "none") continue;
    const b = box(el);
    if (b.width <= 0 || b.height <= 0) continue;
    for (let p = el.parentElement; p && p !== stop; p = p.parentElement) {
      const o = getComputedStyle(p).overflowY;
      if (o === "visible") continue;
      const a = box(p);
      const cut =
        o === "hidden" || o === "clip"
          ? b.top < a.top - 0.5 || b.bottom > a.bottom + 0.5
          : a.bottom - a.top < b.bottom - b.top - 0.5;
      if (cut) {
        const name = (typeof el.className === "string" && el.className.trim()) || el.tagName.toLowerCase();
        out.push(`${name}: ${(el.textContent || "").trim().slice(0, 40)}`);
        break;
      }
    }
  }
  return out;
}

/**
 * The start screen (v0.21.0 final review finding 21, K3; and the archetype
 * overflow found retaking the README). Self-contained.
 *
 * GATED:
 *   - `fold` (only when asked, `{ fold: true }`: the gate asks at 1366x768):
 *     the first `.start` button that begins a run has its bottom inside the
 *     window, without scrolling;
 *   - `overflowing`: an element of the start screen whose box runs past the
 *     window's left or right edge, or out of the start card's sides (the
 *     archetype fieldset grew to its min-content, 1048px in a 518px card);
 *   - `clipped`: an element of the start screen cut sideways by a clip --
 *     its own `overflow-x` hides content wider than its box (an ellipsized
 *     description), or an ancestor that clips without scrolling cuts its box.
 * A visually-hidden control (a 1px clipped radio) is neither.
 */
export function probeStart({ fold = true } = {}) {
  const start = document.querySelector(".start");
  if (!start) return { present: false, failures: [] };
  const primary = start.querySelector("button[type=submit]") || start.querySelector("button");
  const b = primary ? primary.getBoundingClientRect() : null;
  const failures = [];
  if (!b) failures.push("the start screen has no button");
  else if (fold && b.bottom > innerHeight + 0.5) failures.push(`the start button is below the fold (${Math.round(b.bottom)} of ${innerHeight})`);

  const name = (el) => (typeof el.className === "string" && el.className.trim()) || el.tagName.toLowerCase();
  const card = start.querySelector(".start__card");
  const cb = card ? card.getBoundingClientRect() : null;
  const hiddenControl = (el) => {
    const s = getComputedStyle(el);
    return s.position === "absolute" && (s.clip === "rect(0px, 0px, 0px, 0px)" || el.getBoundingClientRect().width <= 1);
  };
  const overflowing = new Set();
  const clipped = new Set();
  for (const el of [start, ...start.querySelectorAll("*")]) {
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden" || hiddenControl(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    if (r.left < -0.5 || r.right > innerWidth + 0.5) overflowing.add(`${name(el)} (${Math.round(r.left)}..${Math.round(r.right)} of ${innerWidth})`);
    else if (cb && card !== el && card.contains(el) && (r.left < cb.left - 0.5 || r.right > cb.right + 0.5)) {
      overflowing.add(`${name(el)} (${Math.round(r.left)}..${Math.round(r.right)}, card ${Math.round(cb.left)}..${Math.round(cb.right)})`);
    }
    const ox = s.overflowX;
    if ((ox === "hidden" || ox === "clip") && el.scrollWidth > el.clientWidth + 1) clipped.add(`${name(el)} hides ${el.scrollWidth - el.clientWidth}px`);
    for (let p = el.parentElement; p && p !== start.parentElement; p = p.parentElement) {
      const po = getComputedStyle(p).overflowX;
      if (po !== "hidden" && po !== "clip") continue;
      const a = p.getBoundingClientRect();
      if (r.left < a.left - 0.5 || r.right > a.right + 0.5) {
        clipped.add(`${name(el)} cut by ${name(p)}`);
        break;
      }
    }
  }
  if (overflowing.size) failures.push(`start screen content runs past its edge: ${[...overflowing].slice(0, 6).join("; ")}`);
  if (clipped.size) failures.push(`start screen content is clipped: ${[...clipped].slice(0, 6).join("; ")}`);
  return {
    present: true,
    failures,
    bottom: b ? Math.round(b.bottom) : null,
    label: primary ? primary.textContent.trim().slice(0, 40) : "",
    overflowing: [...overflowing],
    clipped: [...clipped],
  };
}

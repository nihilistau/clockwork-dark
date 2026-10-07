/**
 * The play screen's layout gate (v0.21.0, spec §3.4; T6 review finding 3).
 *
 *   node ui/tools/layout-check.mjs --story <slug> --url http://127.0.0.1:<port>
 *       --runs <root>/runs.json --out <dir> [--run <tag> ...]
 *       [--channel chrome | --executable-path <browser>]
 *       [--panels '<json>'] [--roll <recorded socket fixture.json>]
 *
 * Expects `python scripts/screenshot_runs.py --root <root> --serve <slug>
 * --exit-with-parent` (start it as a background task, never a bare `&`)
 * already running, as `screenshots.mjs` does. For every run of the story in
 * runs.json (or the `--run` tags named), at every size below, it continues
 * the run from the save browser, runs `probeLayout` (layout-probe.js) in the
 * page, and writes `<out>/<story>-<run>-<size>.png` and
 * `<out>/<story>-layout.json`. It prints one line per probe and exits 1 when
 * any probe has a failure, so T7 and the release can gate on it.
 *
 * The sizes: the spec's three (1366x768, the reference window; 900x600, the
 * size that measured the crushed choices; 390x844, a phone), each STRICT --
 * the compose box and the first chip must be fully on screen -- plus a
 * landscape phone, 844x390, where the floors outgrow the column and the
 * column is ALLOWED to scroll, so only overlap, reachability and the page's
 * own scroll are gated there.
 *
 * With the people strip in the stage, the scene plate must keep most of its
 * own 12vh floor (T14).
 *
 * The start screen is probed first, at the three strict sizes (`probeStart`):
 * nothing past the window's sides or the card's, nothing cut sideways by a
 * clip, and at 1366x768 the Begin button above the fold. Every play probe
 * also gates the log's whole lines (`logLines`) and the people strip
 * (`people`: inside the window, no card cut at its edge).
 *
 * The shelf region's panels must show their heading inside the shelf and the
 * viewport, scrolled to if need be (T9: the job panel at 844x390). The
 * ledger region's panels (the sheet column, under the Ledger) are gated
 * at every size too: each heading must scroll into the viewport -- where
 * the tab bar shows (900px wide and under), after pressing the Sheet tab, photographed as `...-sheet.png`.
 *
 * TWO TOOL-ONLY OVERRIDES (T9 fix round 1). Each acts on the probe's own
 * browser context and nothing else: no server, save or repo file changes,
 * and a real player's client and server are untouched.
 *
 *   --panels '<json>'  answers the story's `ui.panels` declaration (a JSON
 *       list, as in game.yaml) by rewriting this context's `/api/games`
 *       answer for `--story` only -- how a panel is photographed before its
 *       story declares it. The override is recorded in the layout JSON, and
 *       every PNG and the JSON are suffixed `-declared`.
 *   --roll <fixture>   after the main probe, delivers the first recorded
 *       `dice_result` in a recorded socket fixture (e.g.
 *       tests/fixtures/local_mode/hue-and-cry/socket_stream_turn.json) to the
 *       page over its own WebSocket (Playwright's routeWebSocket, passing
 *       every real frame through), waits for core's roll card, probes again
 *       -- the card must meet no chip and not the compose box, sit inside
 *       the main column, be wholly in view (also with the column scrolled to
 *       its end, T14), and stay off the log when the stage could hold it --
 *       and photographs `...-<size>-roll.png`. A story
 *       whose plugin draws rolls itself (`ownsPanels: ["rolls"]`) shows no
 *       card: do not pass --roll for it.
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { chromium } from "playwright-core";

import { clippedControlsIn, probeHeader, probeLayout, probeStart, shelfHeadingVisible } from "./layout-probe.js";

export const SIZES = [
  { name: "1366x768", width: 1366, height: 768, phone: false, strict: true },
  { name: "900x600", width: 900, height: 600, phone: false, strict: true },
  { name: "390x844", width: 390, height: 844, phone: true, strict: true },
  { name: "844x390", width: 844, height: 390, phone: true, strict: false },
];

const FLAGS = ["story", "url", "runs", "out", "run", "channel", "executable-path", "panels", "roll"];

function args(argv) {
  const out = { run: [], channel: "chrome" };
  for (let i = 0; i < argv.length; i += 1) {
    if (!argv[i].startsWith("--") || !FLAGS.includes(argv[i].slice(2))) {
      throw new Error(`unknown argument ${argv[i]} (flags: ${FLAGS.map((f) => `--${f}`).join(" ")})`);
    }
    const key = argv[i].slice(2);
    const value = argv[i + 1];
    if (value === undefined || value.startsWith("--")) throw new Error(`--${key} needs a value`);
    i += 1;
    if (key === "run") out.run.push(value);
    else out[key] = value;
  }
  for (const need of ["story", "url", "runs", "out"]) {
    if (!out[need]) throw new Error(`--${need} is required`);
  }
  if (out.panels !== undefined) {
    out.panels = JSON.parse(out.panels);
    if (!Array.isArray(out.panels)) throw new Error("--panels takes a JSON list, as ui.panels in game.yaml");
  }
  out.suffix = out.panels ? "-declared" : "";
  if (out.roll) out.roll = recordedRoll(resolve(out.roll));
  return out;
}

/** The first `dice_result` event's argument in a recorded socket fixture. */
function recordedRoll(path) {
  const found = [];
  const walk = (node) => {
    if (Array.isArray(node)) node.forEach(walk);
    else if (node && typeof node === "object") {
      if (node.name === "dice_result" && Array.isArray(node.args)) found.push(node.args[0]);
      Object.values(node).forEach(walk);
    }
  };
  walk(JSON.parse(readFileSync(path, "utf8")));
  if (!found.length) throw new Error(`--roll: no dice_result in ${path}`);
  return found[0];
}

async function probe(browser, opts, tag, player, size) {
  const context = await browser.newContext({
    viewport: { width: size.width, height: size.height },
    deviceScaleFactor: 1,
    isMobile: size.phone,
    hasTouch: size.phone,
  });
  let socket = null;
  if (opts.panels) {
    await context.route("**/api/games", async (route) => {
      const res = await route.fetch();
      const body = await res.json();
      for (const game of body.games || []) {
        if (game.id === opts.story) game.ui = { ...(game.ui || {}), panels: opts.panels };
      }
      await route.fulfill({ response: res, json: body });
    });
  }
  if (opts.roll) {
    // Every real frame passes through (no onMessage handler is set); the
    // probe only ever ADDS one recorded event, toward the page.
    await context.routeWebSocket(/\/socket\.io\//, (ws) => {
      ws.connectToServer();
      socket = ws;
    });
  }
  try {
    await context.addInitScript((slug) => {
      try {
        localStorage.setItem("clockwork_prefs", JSON.stringify({ reduceMotion: true, showReasoning: false }));
        localStorage.setItem("clockwork_onboarded", "1");
        localStorage.setItem(`clockwork_onboarded:${slug}`, "1");
        localStorage.removeItem("clockwork_save_id");
      } catch { /* a probe without storage still draws */ }
    }, opts.story);
    const page = await context.newPage();
    await page.goto(opts.url, { waitUntil: "networkidle" });
    await page.waitForSelector(".start__continue", { timeout: 30000 });
    await page.click(".start__continue");
    await page.locator(".saverow", { hasText: player }).getByRole("button", { name: "Continue" }).click();
    await page.waitForSelector(".scene", { timeout: 30000 });
    await page.waitForFunction(() => !document.querySelector(".is-streaming"), null, { timeout: 30000 });
    await page.evaluate(async () => { await document.fonts.ready; });
    await page.waitForTimeout(800);
    const result = await page.evaluate(probeLayout, size.strict);
    result.plate = await page.evaluate(platePastStrip);
    if (result.plate?.failure) result.failures.push(result.plate.failure);
    const header = await page.evaluate(probeHeader);
    for (const failure of header.failures) result.failures.push(`header: ${failure}`);
    result.header = header;
    const file = join(opts.out, `${opts.story}-${tag}-${size.name}${opts.suffix}.png`);
    await page.screenshot({ path: file, animations: "disabled" });
    const shelf = await shelfPanels(page, opts, tag, size);
    if (shelf.missing.length) result.failures.push(`shelf panels not reachable: ${shelf.missing.join(", ")}`);
    const roll = opts.roll ? await rollCard(page, opts, tag, size, socket) : null;
    if (roll) for (const failure of roll.failures) result.failures.push(`roll: ${failure}`);
    const ledger = await ledgerPanels(page, opts, tag, size);
    if (ledger.missing.length) result.failures.push(`ledger panels not reachable: ${ledger.missing.join(", ")}`);
    if (ledger.clipped?.length) result.failures.push(`ledger controls cut off unreachably: ${ledger.clipped.join("; ")}`);
    return { ...result, shelf, roll, ledger, png: file, override: opts.panels ? { panels: opts.panels } : null };
  } finally {
    await context.close();
  }
}

/**
 * The scene plate beside the people strip (T14, T9 review finding 5): with
 * the strip in the stage, the plate (the stage's first child) must keep at
 * least most of its own 12vh floor (--visual-height), rather than being
 * squeezed under the strip to a sliver. Null when the stage holds no strip.
 *
 * A plate the stylesheet HIDES is not squeezed: under 640px tall the plate
 * gives way to the strip whole (index.css, final review finding 19), so a
 * `display: none` plate is reported, never failed. A sliver still fails.
 */
function platePastStrip() {
  const stage = document.querySelector(".stage-area");
  const strip = stage?.querySelector(":scope > .people");
  const plate = stage?.firstElementChild;
  if (!strip || !plate || plate === strip) return null;
  if (getComputedStyle(plate).display === "none") {
    return { height: 0, hidden: true, floor: Math.round(0.12 * innerHeight), strip: Math.round(strip.getBoundingClientRect().height) };
  }
  const floor = 0.12 * innerHeight;
  const height = plate.getBoundingClientRect().height;
  const out = { height: Math.round(height), floor: Math.round(floor), strip: Math.round(strip.getBoundingClientRect().height) };
  if (height < floor * 0.85) out.failure = `the scene plate is ${out.height}px under the people strip (its floor is ${out.floor}px)`;
  return out;
}

/**
 * The shelf region's panels (v0.21.0 T9; T6 review issue B, T7 review
 * finding 5): the current move's panels -- the job panel above all -- must
 * have their heading ON SCREEN, inside the shelf's own box (a shelf crushed
 * to 0px shows nothing) and inside the column's view of the viewport. `atRest` is whether it was
 * so before any scrolling (information: at 844x390 the column may scroll);
 * the gate is that scrolling it into view brings it whole. A heading that
 * needed the scroll is photographed as `...-<size>-shelf.png`.
 */
async function shelfPanels(page, opts, tag, size) {
  const ids = await page.$$eval(".shelf > section", (els) => els.map((el) => el.getAttribute("aria-labelledby")));
  if (ids.length === 0) return { panels: [], missing: [], atRest: {}, png: null };
  const visible = shelfHeadingVisible;
  const atRest = {};
  const missing = [];
  let scrolled = false;
  for (const id of ids) {
    atRest[id] = await page.evaluate(visible, id);
    if (atRest[id]) continue;
    scrolled = true;
    await page.evaluate((headingId) => document.getElementById(headingId)?.scrollIntoView({ block: "nearest" }), id);
    if (!(await page.evaluate(visible, id))) missing.push(id);
  }
  let png = null;
  if (scrolled) {
    png = join(opts.out, `${opts.story}-${tag}-${size.name}${opts.suffix}-shelf.png`);
    await page.screenshot({ path: png, animations: "disabled" });
  }
  return { panels: ids, missing, atRest, png };
}

/**
 * The roll card (`--roll`, T9 fix round 1): one recorded `dice_result`
 * delivered to the page as Socket.IO's own event frame, the card awaited,
 * the column scrolled back to its top (where the toast region lies), the
 * layout probed again with the card up, and photographed.
 *
 * Two more gates since T14 (T9 re-review R1-1, R1-2):
 *   - the card must be wholly in the viewport, at rest AND with the column
 *     scrolled to its end (a player who scrolled down to the choices; the
 *     column scrolls at 844x390). Where the column does scroll, the second
 *     roll is photographed as `...-<size>-roll-scrolled.png`;
 *   - when the stage is at least as tall as the card, the card must not
 *     meet the narrative log (it would sit over the newest prose).
 */
async function rollCard(page, opts, tag, size, socket) {
  if (!socket) return { shown: false, failures: ["no game socket to deliver the roll on"], png: null };
  await page.evaluate(() => document.querySelector(".scene__col--main")?.scrollTo(0, 0));
  const first = await deliverRoll(page, opts, socket, true);
  if (!first) return { shown: false, failures: ["no roll card appeared"], png: null };
  const result = await page.evaluate(probeLayout, size.strict);
  const failures = [...result.failures, ...first.failures];
  const png = join(opts.out, `${opts.story}-${tag}-${size.name}${opts.suffix}-roll.png`);
  await page.screenshot({ path: png, animations: "disabled" });
  let scrolled = null;
  const scrolls = await page.evaluate(() => {
    const col = document.querySelector(".scene__col--main");
    return Boolean(col) && col.scrollHeight > col.clientHeight + 1;
  });
  if (scrolls) {
    await page.evaluate(() => {
      const col = document.querySelector(".scene__col--main");
      col.scrollTo(0, col.scrollHeight);
    });
    const again = await deliverRoll(page, opts, socket, false);
    if (!again) {
      failures.push("scrolled: no roll card appeared");
    } else {
      const probed = await page.evaluate(probeLayout, false);
      for (const f of [...probed.failures, ...again.failures]) failures.push(`scrolled: ${f}`);
      const scrolledPng = join(opts.out, `${opts.story}-${tag}-${size.name}${opts.suffix}-roll-scrolled.png`);
      await page.screenshot({ path: scrolledPng, animations: "disabled" });
      scrolled = { card: again.card, png: scrolledPng };
    }
    await page.evaluate(() => document.querySelector(".scene__col--main")?.scrollTo(0, 0));
  }
  return { shown: true, card: first.card, failures, toastOverlaps: result.toastOverlaps, png, scrolled };
}

/**
 * One recorded roll delivered and its card measured: in view, and -- at rest,
 * where the stage is in view -- clear of the log when the stage can hold it.
 * Scrolled to the choices, the stage is above the view, and the card is
 * pinned over whatever is at the top of it (index.css, R1-2).
 */
async function deliverRoll(page, opts, socket, atRest) {
  socket.send(`42${JSON.stringify(["dice_result", opts.roll])}`);
  try {
    await page.waitForFunction(() => {
      const card = document.querySelector(".rollcard");
      return card && card.getAnimations().every((a) => a.playState !== "running");
    }, null, { timeout: 5000 });
  } catch {
    return null;
  }
  await page.waitForTimeout(300);
  return page.$eval(".rollcard", (el, rest) => {
    const b = el.getBoundingClientRect();
    const card = { top: b.top, bottom: b.bottom, left: b.left, right: b.right, height: b.height, text: el.innerText.replace(/\s+/g, " ") };
    const failures = [];
    if (b.top < -0.5 || b.bottom > innerHeight + 0.5 || b.left < -0.5 || b.right > innerWidth + 0.5) {
      failures.push(`the roll card is not wholly in view (${Math.round(b.top)}..${Math.round(b.bottom)} of ${innerHeight})`);
    }
    const stage = document.querySelector(".stage-area")?.getBoundingClientRect();
    const log = document.querySelector(".scene__col--main > .log")?.getBoundingClientRect();
    if (rest && stage && log && stage.height >= b.height && log.height > 0) {
      const meets = b.left < log.right && b.right > log.left && b.top < log.bottom && b.bottom > log.top;
      if (meets) failures.push(`the roll card covers the narrative log though the stage (${Math.round(stage.height)}px) could hold it (${Math.round(b.height)}px)`);
    }
    return { card, failures };
  }, atRest);
}

/**
 * The ledger region's panels (v0.21.0 T7): each heading must be reachable --
 * through the Sheet tab where the tab bar shows, which is where the casing
 * board now lives. Each is scrolled into view and must then have a box
 * inside the viewport. The Sheet tab is photographed as
 * `...-<size>-sheet.png`.
 */
async function ledgerPanels(page, opts, tag, size) {
  const ids = await page.$$eval(".ledger-panels > section", (els) => els.map((el) => el.getAttribute("aria-labelledby")));
  if (ids.length === 0) return { panels: [], missing: [], png: null };
  let png = null;
  // The tab bar shows on narrow viewports (900px and under), phone or not.
  const tabs = await page.locator(".tabbar").isVisible();
  if (tabs) {
    await page.locator(".tabbar").getByRole("button", { name: "Sheet" }).click();
    await page.waitForTimeout(300);
  }
  const missing = [];
  for (const id of ids) {
    // Inside the viewport AND inside the sheet column's visible box (final
    // review finding 23): a raw box past the column's own edge is clipped.
    const seen = await page.evaluate((headingId) => {
      const h = document.getElementById(headingId);
      if (!h) return false;
      h.scrollIntoView({ block: "nearest" });
      const b = h.getBoundingClientRect();
      const col = h.closest(".scene__col--sheet");
      const c = col ? col.getBoundingClientRect() : { top: 0, bottom: innerHeight };
      return (
        b.height > 0 && b.width > 0 && b.top >= Math.max(0, c.top) - 0.5 &&
        b.bottom <= Math.min(innerHeight, c.bottom) + 0.5
      );
    }, id);
    if (!seen) missing.push(id);
  }
  // The ledger's controls, walked as the main column's are (finding 23).
  const clipped = await page.evaluate(clippedControlsIn, ".scene__col--sheet");
  if (tabs) {
    png = join(opts.out, `${opts.story}-${tag}-${size.name}${opts.suffix}-sheet.png`);
    await page.screenshot({ path: png, animations: "disabled" });
  }
  return { panels: ids, missing, clipped, png };
}

/**
 * The start screen, at each STRICT size (1366x768, 900x600, 390x844): no
 * element past the window's sides or the card's, and none cut sideways by a
 * clip (v0.21.0: the archetype descriptions ran off the card). At 1366x768
 * the Begin button must also be fully on screen without scrolling (final
 * review finding 21, K3), for every story; at the other two the card may
 * scroll to it.
 */
async function startScreen(browser, opts, size) {
  const context = await browser.newContext({
    viewport: { width: size.width, height: size.height },
    deviceScaleFactor: 1,
    isMobile: size.phone,
    hasTouch: size.phone,
  });
  try {
    await context.addInitScript((slug) => {
      try {
        localStorage.setItem("clockwork_prefs", JSON.stringify({ reduceMotion: true, showReasoning: false }));
        localStorage.setItem("clockwork_onboarded", "1");
        localStorage.setItem(`clockwork_onboarded:${slug}`, "1");
      } catch { /* a probe without storage still draws */ }
    }, opts.story);
    const page = await context.newPage();
    await page.goto(opts.url, { waitUntil: "networkidle" });
    await page.waitForSelector(".start__continue", { timeout: 30000 });
    await page.evaluate(async () => { await document.fonts.ready; });
    await page.waitForTimeout(500);
    const result = await page.evaluate(probeStart, { fold: size.name === "1366x768" });
    await page.screenshot({ path: join(opts.out, `${opts.story}-start-${size.name}${opts.suffix}.png`), animations: "disabled" });
    return result;
  } finally {
    await context.close();
  }
}

async function main() {
  const opts = args(process.argv.slice(2));
  opts.out = resolve(opts.out);
  mkdirSync(opts.out, { recursive: true });
  const runs = JSON.parse(readFileSync(resolve(opts.runs), "utf8"))[opts.story] || {};
  const tags = opts.run.length ? opts.run : Object.keys(runs).sort();
  if (tags.length === 0) throw new Error(`runs.json has no run for ${opts.story}`);

  process.env.PLAYWRIGHT_CHROMIUM_USE_HEADLESS_NEW = "1";
  const executablePath = opts["executable-path"];
  const browser = await chromium.launch(
    executablePath ? { executablePath, headless: true } : { channel: opts.channel, headless: true }
  );
  const results = {};
  let failed = 0;
  try {
    for (const size of SIZES.filter((s) => s.strict)) {
      const start = await startScreen(browser, opts, size);
      results[`${opts.story}/start/${size.name}`] = start;
      if (start.failures.length) failed += 1;
      console.log(`${start.failures.length ? "FAIL" : "ok  "} ${opts.story}/start ${size.name}  [begin bottom ${start.bottom}px]` +
        (start.failures.length ? `  ${start.failures.join(" | ")}` : ""));
    }
    for (const tag of tags) {
      const player = runs[tag]?.player;
      if (!player) throw new Error(`runs.json has no ${opts.story}/${tag}`);
      for (const size of SIZES) {
        const result = await probe(browser, opts, tag, player, size);
        results[`${opts.story}/${tag}/${size.name}`] = result;
        if (result.failures.length) failed += 1;
        console.log(
          `${result.failures.length ? "FAIL" : "ok  "} ${opts.story}/${tag} ${size.name}` +
            (result.roll ? `  [roll card ${result.roll.shown ? "shown" : "MISSING"}]` : "") +
            (result.plate ? `  [plate ${result.plate.hidden ? "gives way" : `${result.plate.height}px`}, strip ${result.plate.strip}px]` : "") +
            (result.header?.present ? `  [header gap ${result.header.gap}px${result.header.titleClipped ? ", name clipped" : ""}${result.header.chip ? `, chip "${result.header.chip}"` : ""}]` : "") +
            (result.logFloor ? `  [log ${result.logFloor.log}px, floor ${result.logFloor.floor}px]` : "") +
            (result.logLines ? `  [log lines ${result.logLines.whole}/${result.logLines.lines}${result.logLines.cutTop ? ", top cut" : ""}]` : "") +
            (result.failures.length ? `  ${result.failures.join(" | ")}` : "") +
            // Advisories at desktop sizes, printed and never failed (finding 19).
            (!size.phone && result.advisories?.length ? `  advisory: ${result.advisories.join("; ")}` : "")
        );
      }
    }
  } finally {
    await browser.close();
    writeFileSync(join(opts.out, `${opts.story}-layout${opts.suffix}.json`), JSON.stringify(results, null, 2));
  }
  if (failed) process.exitCode = 1;
}

main().catch((err) => {
  console.error(`layout-check: ${err.message}`);
  process.exit(2);
});

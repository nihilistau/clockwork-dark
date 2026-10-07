/**
 * The README's captures, written as files (v0.21.0, spec §11).
 *
 *   npm run screenshots --prefix ui -- --story <slug> --url http://127.0.0.1:<port>
 *       --runs <root>/runs.json --out ../docs/images [--only <name>]
 *       [--channel chrome | --executable-path <browser>]
 *
 * Expects `python scripts/screenshot_runs.py --root <root> --serve <slug>
 * --exit-with-parent` (start it as a background task, never a bare `&`)
 * already running (it starts no server). Drives the browser ALREADY
 * INSTALLED: the installed Chrome by default (`--channel msedge` to use
 * Edge -- Edge 154 exits at once headless on the owner's machine), or any
 * Chromium binary by `--executable-path` (a distro Chromium on Linux).
 * playwright-core ships no browser and downloads none.
 */
import { mkdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { chromium } from "playwright-core";

const DESKTOP = { width: 1366, height: 768 };
const PHONE = { width: 390, height: 844 };

/**
 * Every UI capture the README carries: thirteen. `run` names a runs.json tag.
 * `jpeg: true` for the plate-heavy ones (final review finding 22): a painted
 * plate is a photograph, and as PNG the title screen weighed 1.06 MB. They
 * are written as `<name>.jpg` at JPEG_QUALITY; the rest stay PNG.
 */
export const JPEG_QUALITY = 85;
export const CAPTURES = [
  { name: "clockwork-dark-title", story: "clockwork-dark", screen: "title", jpeg: true },
  { name: "clockwork-dark-play", story: "clockwork-dark", run: "play", jpeg: true },
  { name: "clockwork-dark-map", story: "clockwork-dark", run: "play", open: "m" },
  { name: "wicked-garden-play", story: "wicked-garden", run: "play", jpeg: true },
  { name: "wicked-garden-deck", story: "wicked-garden", run: "deck", jpeg: true },
  { name: "neon-city-title", story: "neon-city", screen: "title" },
  { name: "neon-city-play", story: "neon-city", run: "play" },
  { name: "the-long-con-play", story: "the-long-con", run: "play" },
  { name: "hue-and-cry-play", story: "hue-and-cry", run: "play" },
  { name: "hue-and-cry-map", story: "hue-and-cry", run: "play", open: "m" },
  { name: "hue-and-cry-panels", story: "hue-and-cry", run: "panels" },
  { name: "hue-and-cry-phone", story: "hue-and-cry", run: "panels", size: PHONE },
  { name: "dev-story-play", story: "dev-story", run: "play" },
];

/** Every flag the tool takes; any other is refused, never ignored. */
const FLAGS = ["story", "url", "runs", "out", "only", "channel", "executable-path"];

function args(argv) {
  const out = { only: [], channel: "chrome" };
  for (let i = 0; i < argv.length; i += 1) {
    if (!argv[i].startsWith("--") || !FLAGS.includes(argv[i].slice(2))) {
      throw new Error(`unknown argument ${argv[i]} (flags: ${FLAGS.map((f) => `--${f}`).join(" ")})`);
    }
    const key = argv[i].slice(2);
    const value = argv[i + 1];
    if (value === undefined || value.startsWith("--")) throw new Error(`--${key} needs a value`);
    i += 1;
    if (key === "only") out.only.push(value);
    else out[key] = value;
  }
  for (const need of ["story", "url", "runs", "out"]) {
    if (!out[need]) throw new Error(`--${need} is required`);
  }
  return out;
}

async function settle(page) {
  await page.waitForSelector(".scene", { timeout: 30000 });
  await page.waitForFunction(() => !document.querySelector(".is-streaming"), null, { timeout: 30000 });
  await page.evaluate(async () => { await document.fonts.ready; });
  await page.waitForTimeout(500);
}

async function capture(browser, opts, runs, item) {
  const context = await browser.newContext({ viewport: item.size || DESKTOP, deviceScaleFactor: 1 });
  await context.addInitScript((slug) => {
    try {
      localStorage.setItem("clockwork_prefs", JSON.stringify({ reduceMotion: true, showReasoning: false }));
      localStorage.setItem("clockwork_onboarded", "1");
      localStorage.setItem(`clockwork_onboarded:${slug}`, "1");
      localStorage.removeItem("clockwork_save_id");
    } catch { /* a capture without storage still draws */ }
  }, item.story);
  const page = await context.newPage();
  await page.goto(opts.url, { waitUntil: "networkidle" });
  await page.waitForSelector(".start__continue", { timeout: 30000 });
  if (item.run) {
    const player = runs[item.story]?.[item.run]?.player;
    if (!player) throw new Error(`runs.json has no ${item.story}/${item.run}`);
    await page.click(".start__continue");
    const row = page.locator(".saverow", { hasText: player });
    await row.getByRole("button", { name: "Continue" }).click();
    await settle(page);
    if (item.open) {
      await page.keyboard.press(item.open);
      await page.waitForSelector('[role="dialog"]', { timeout: 15000 });
      await page.waitForTimeout(500);
    }
  } else {
    await page.evaluate(async () => { await document.fonts.ready; });
  }
  const file = join(opts.out, `${item.name}.${item.jpeg ? "jpg" : "png"}`);
  await page.screenshot(
    item.jpeg
      ? { path: file, animations: "disabled", type: "jpeg", quality: JPEG_QUALITY }
      : { path: file, animations: "disabled" }
  );
  await context.close();
  return file;
}

async function main() {
  const opts = args(process.argv.slice(2));
  const runs = JSON.parse(readFileSync(resolve(opts.runs), "utf8"));
  mkdirSync(resolve(opts.out), { recursive: true });
  const wanted = CAPTURES.filter(
    (c) => c.story === opts.story && (opts.only.length === 0 || opts.only.includes(c.name))
  );
  if (wanted.length === 0) throw new Error(`no capture for ${opts.story} ${opts.only.join(",")}`);
  // playwright-core 1.48 asks a branded browser for `--headless=old`, which
  // Chrome and Edge 132+ no longer have (the browser exits at once). Its own
  // switch for the new mode keeps every headless flag it adds (hidden
  // scrollbars, muted audio, a fixed hover/pointer profile), so a capture
  // does not depend on the capturing machine's input devices.
  process.env.PLAYWRIGHT_CHROMIUM_USE_HEADLESS_NEW = "1";
  const executablePath = opts["executable-path"];
  const browser = await chromium.launch(
    executablePath ? { executablePath, headless: true } : { channel: opts.channel, headless: true }
  );
  try {
    for (const item of wanted) console.log(await capture(browser, { ...opts, out: resolve(opts.out) }, runs, item));
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(`screenshots: ${err.message}`);
  process.exit(1);
});

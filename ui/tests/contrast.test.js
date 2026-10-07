/**
 * Contrast, measured rather than hoped (v0.21.0, spec §8.3).
 *
 * Each theme's palette is resolved as the files hold it -- `var()` chains
 * with fallbacks, and `color-mix(in srgb, A p%, B)` as the sRGB channel mix
 * (core's derived tokens use it) -- over core's palette, and every pair core
 * draws text on is held to WCAG 2.1: 4.5:1 for text, 3:1 for the marks. The
 * flagship is checked in every phase (`body[data-phase=…]` over its base).
 * A value this cannot resolve fails BY NAME rather than being skipped.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = resolve(process.cwd(), "src");
const read = (rel) => readFileSync(resolve(SRC, rel), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

/** Every innermost `selector { … }` block's custom properties. */
function blocks(rel) {
  const out = [];
  for (const match of read(rel).matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const decls = {};
    for (const d of match[2].matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) decls[d[1]] = d[2].trim();
    if (Object.keys(decls).length) out.push({ selector: match[1].trim(), decls });
  }
  return out;
}

const VARIANT = /\[data-(phase|district)=/;

function palette(files) {
  const table = {};
  for (const rel of files) for (const block of blocks(rel)) if (!VARIANT.test(block.selector)) Object.assign(table, block.decls);
  return table;
}

function variants(files) {
  const out = {};
  for (const rel of files) {
    for (const block of blocks(rel)) {
      const m = block.selector.match(/\[data-(?:phase|district)="?([a-z_-]+)"?\]/);
      if (m) out[m[1]] = { ...(out[m[1]] || {}), ...block.decls };
    }
  }
  return out;
}

const NAMED = { black: [0, 0, 0, 1], white: [255, 255, 255, 1], transparent: [0, 0, 0, 0] };

function parseColor(text, name) {
  const v = text.trim().toLowerCase();
  if (NAMED[v]) return NAMED[v];
  let m = v.match(/^#([0-9a-f]{3,8})$/);
  if (m) {
    let hex = m[1];
    if (hex.length === 3 || hex.length === 4) hex = [...hex].map((c) => c + c).join("");
    const n = (i) => parseInt(hex.slice(i, i + 2), 16);
    return [n(0), n(2), n(4), hex.length === 8 ? n(6) / 255 : 1];
  }
  m = v.match(/^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$/);
  if (m) return [Number(m[1]), Number(m[2]), Number(m[3]), m[4] === undefined ? 1 : Number(m[4])];
  throw new Error(`${name}: cannot resolve ${JSON.stringify(text)}`);
}

function resolveValue(text, table, name, depth = 0) {
  if (depth > 20) throw new Error(`${name}: var() chain too deep`);
  const v = text.trim();
  let m = v.match(/^var\(\s*(--[a-z0-9-]+)\s*(?:,\s*(.+))?\)$/);
  if (m) {
    if (table[m[1]] !== undefined) return resolveValue(table[m[1]], table, m[1], depth + 1);
    if (m[2] !== undefined) return resolveValue(m[2], table, name, depth + 1);
    throw new Error(`${name}: ${m[1]} is not defined`);
  }
  m = v.match(/^color-mix\(\s*in srgb\s*,\s*(.+?)\s+([\d.]+)%\s*,\s*(.+)\)$/);
  if (m) {
    const a = resolveValue(m[1], table, name, depth + 1);
    const b = resolveValue(m[3], table, name, depth + 1);
    const p = Number(m[2]) / 100;
    // As CSS Color 5 mixes: premultiplied by alpha, then un-premultiplied
    // (so mixing with `transparent` fades a colour rather than darkening it).
    const alpha = a[3] * p + b[3] * (1 - p);
    if (alpha === 0) return [0, 0, 0, 0];
    const rgb = [0, 1, 2].map((i) => (a[i] * a[3] * p + b[i] * b[3] * (1 - p)) / alpha);
    return [...rgb, alpha];
  }
  return parseColor(v, name);
}

function over(top, bottom) {
  const a = top[3];
  return [0, 1, 2].map((i) => top[i] * a + bottom[i] * (1 - a)).concat(1);
}

function luminance([r, g, b]) {
  const lin = (c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function ratio(fg, bg) {
  const [hi, lo] = [luminance(fg), luminance(bg)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const PAIRS = [
  ["--text-body", "--surface-card", 4.5],
  ["--text-body", "--surface-narrative", 4.5],
  // The chip's face is a gradient from the lifted card down to the card:
  // the lift is core's `color-mix`, so this pair runs the mix in every theme.
  ["--text-body", "--surface-card-lift", 4.5],
  ["--text-narration", "--surface-narrative", 4.5],
  ["--text-muted", "--surface-scene", 4.5],
  ["--panel-ink", "--panel-paper", 4.5],
  ["--panel-danger", "--panel-paper", 4.5],
  // A panel's quieter line (summary, done stage, a house's type, the roll's
  // figures): on the panel's paper, not the scene (T14: HUE & CRY's parchment).
  ["--panel-muted", "--panel-paper", 4.5],
  ["--panel-mark", "--panel-paper", 3],
  // The focus ring is drawn outside the control (outline-offset 2px), on the
  // scene; WCAG 2.1 1.4.11 wants 3:1 for a focus indicator (T13 review 1).
  ["--focus-ring", "--surface-scene", 3],
  // Inside a panel the ring is drawn on the panel's paper (T14 review 1).
  ["--panel-focus", "--panel-paper", 3],
];

const CORE = ["styles/tokens.css"];

/** Each theme's palette files. */
export const THEMES = {
  core: [],
  _engine: ["stories/_engine/theme/tokens.css"],
  "clockwork-dark": ["stories/clockwork-dark/theme/colors.css", "stories/clockwork-dark/theme/phases.css"],
  "wicked-garden": ["stories/wicked-garden/theme/tokens.css"],
  "neon-city": ["stories/neon-city/theme/tokens.css"],
  "the-long-con": ["stories/the-long-con/theme/tokens.css"],
  "hue-and-cry": ["stories/hue-and-cry/theme/tokens.css"],
};

function check(table, label) {
  const scene = over(resolveValue("var(--surface-scene)", table, "--surface-scene"), [0, 0, 0, 1]);
  for (const [fgName, bgName, floor] of PAIRS) {
    const bg = over(resolveValue(`var(${bgName})`, table, bgName), scene);
    const fg = over(resolveValue(`var(${fgName})`, table, fgName), bg);
    const measured = ratio(fg, bg);
    expect(measured, `${label}: ${fgName} on ${bgName} is ${measured.toFixed(2)}:1, under ${floor}:1`).toBeGreaterThanOrEqual(floor);
  }
}

describe("the resolver", () => {
  it("computes color-mix as the sRGB channel mix (core's --surface-card-lift)", () => {
    // Core's --surface-card 84% with its --text-on-dark, by hand.
    const table = palette(CORE);
    const card = parseColor(table["--surface-card"], "--surface-card");
    const ink = resolveValue("var(--text-on-dark)", table, "--text-on-dark");
    const want = [0, 1, 2].map((i) => card[i] * 0.84 + ink[i] * 0.16);
    const got = resolveValue("var(--surface-card-lift)", table, "--surface-card-lift");
    for (const i of [0, 1, 2]) expect(got[i]).toBeCloseTo(want[i], 6);
    expect(got[0]).not.toBe(card[0]);
  });

  it("mixes a translucent colour premultiplied, as CSS does", () => {
    // White half into transparent is half-transparent WHITE, not grey.
    expect(resolveValue("color-mix(in srgb, #ffffff 50%, transparent)", {}, "--probe")).toEqual([255, 255, 255, 0.5]);
    expect(resolveValue("color-mix(in srgb, rgba(0, 0, 0, 0.5) 50%, #ffffff)", {}, "--probe").map((v) => Math.round(v * 1000) / 1000))
      .toEqual([170, 170, 170, 0.75]);
  });
});

describe("contrast", () => {
  for (const [theme, files] of Object.entries(THEMES)) {
    it(`${theme}: every text pair core draws`, () => {
      check({ ...palette(CORE), ...palette(files) }, theme);
    });
    for (const [variant, decls] of Object.entries(variants(files))) {
      it(`${theme} [${variant}]: every text pair core draws`, () => {
        check({ ...palette(CORE), ...palette(files), ...decls }, `${theme} ${variant}`);
      });
    }
  }
});

describe("text on a panel's paper reads the panel's tokens", () => {
  // The contrast pairs above hold --panel-ink and --panel-muted on
  // --panel-paper; a core rule colouring a panel's text with a --text-*
  // token (drawn for the dark scene) escapes them. On HUE & CRY's parchment
  // that was 2:1 (T14). The encounter's approach buttons and the negotiation
  // keep their own dark faces, so they are not panel paper.
  const ON_PAPER = /\.(?:panel__|panel--|casing__|poster__|job__|people__(?:card|more|doing|who)|rollcard|encpanel__(?:terms|intro))/;
  it("no core rule on panel paper colours its text with a --text-* token", () => {
    // Every `color:` declaration (`blocks` keeps custom properties only).
    const text = read("styles/index.css");
    const bad = [];
    for (const match of text.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const selector = match[1].trim();
      if (!ON_PAPER.test(selector)) continue;
      for (const d of match[2].matchAll(/(?:^|;)\s*color\s*:\s*([^;]+)/g)) {
        if (/var\(--text-/.test(d[1])) bad.push(`${selector} { color: ${d[1].trim()} }`);
      }
    }
    expect(bad).toEqual([]);
  });
});

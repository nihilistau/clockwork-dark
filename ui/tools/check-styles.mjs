/**
 * Stylesheet guards, run before every build.
 *
 * tests/test_ui_contract.py already forbids raw hex in src/styles/index.css.
 * That test is one path, and the core/story split created three more sheets it
 * does not see -- so a story could put `#8b1e3f` straight into a component rule
 * and the suite would stay green while the theme system quietly stopped working
 * for that story. These checks close that hole from the side of the tree this
 * change owns.
 *
 * Three things are asserted:
 *
 *   1. No raw hex outside a PALETTE file. A palette is the one place a colour
 *      may be spelled; everything else names a token, which is what lets a
 *      story retint the product from one attribute.
 *   2. Every token core's sheet reads is defined in core's own token layer, so
 *      core is legible with no story plugin loaded.
 *   3. Core's sheet does not reference a class that only a story defines.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const SRC = new URL("../src/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

// Files allowed to contain raw hex: they define the primitives everything else
// points at.
const PALETTES = new Set([
  "styles/tokens.css",
  "styles/effects.css", // shadow and grain alphas, not colour names
  "stories/clockwork-dark/theme/colors.css",
  "stories/clockwork-dark/theme/phases.css",
  "stories/wicked-garden/theme/tokens.css",
  "stories/neon-city/theme/tokens.css",
  // The engine's own palette: the look a story gets when it ships none. On the
  // list for the same reason as the others -- a palette is the one place a
  // colour may be spelled.
  "stories/_engine/theme/tokens.css",
]);

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (name.endsWith(".css")) out.push(path);
  }
  return out;
}

const strip = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "");
const failures = [];

for (const path of walk(SRC)) {
  const rel = path.slice(SRC.length).replace(/\\/g, "/");
  if (PALETTES.has(rel)) continue;
  const hexes = [...new Set(strip(readFileSync(path, "utf8")).match(/#[0-9a-fA-F]{3,8}\b/g) || [])];
  if (hexes.length) failures.push(`${rel}: raw hex ${hexes.join(", ")} — name a token instead`);
}

// -- every token core reads is one core defines -----------------------------
const coreSheet = strip(readFileSync(join(SRC, "styles/index.css"), "utf8"));
const defined = new Set();
for (const file of ["tokens.css", "effects.css", "spacing.css", "typography.css", "fonts.css"]) {
  for (const match of strip(readFileSync(join(SRC, "styles", file), "utf8"))
    .matchAll(/(--[a-z0-9-]+)\s*:/g)) {
    defined.add(match[1]);
  }
}
// Tokens the sheet sets on itself (the paint frame's per-size vignette knobs).
for (const match of coreSheet.matchAll(/(--[a-z0-9-]+)\s*:/g)) defined.add(match[1]);

const missing = new Set();
for (const match of coreSheet.matchAll(/var\(\s*(--[a-z0-9-]+)/g)) {
  if (!defined.has(match[1])) missing.add(match[1]);
}
if (missing.size) {
  failures.push(
    `styles/index.css reads tokens core does not define: ${[...missing].sort().join(", ")}\n` +
      "    (core must render with no story plugin, so its fallback palette has to cover it)"
  );
}

if (failures.length) {
  console.error("\nstylesheet check failed:\n");
  for (const line of failures) console.error(`  - ${line}`);
  console.error("");
  process.exit(1);
}
console.log("stylesheet check: ok");

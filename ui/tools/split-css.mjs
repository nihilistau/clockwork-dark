/**
 * One-shot partition of the legacy monolithic stylesheet.
 *
 * WHY a script and not hand editing: index.css is ~4,800 lines written in two
 * passes, so story rules and core rules are interleaved and a hand split would
 * silently drop or reorder rules. This walks the real block structure, splits
 * grouped selectors (which are equivalent to separate rules, so splitting them
 * cannot change meaning), and asserts that every byte of declaration text lands
 * in exactly one output.
 *
 * ALREADY RUN. Its input -- the single 4,836-line src/styles/index.css -- no
 * longer exists; the outputs are src/styles/index.css (core) and
 * src/stories/clockwork-dark/theme/clockwork-dark.css (the flagship). It is
 * kept because it is the provenance of that split: it says exactly which class
 * blocks were judged story-owned, and it is the tool to reach for the next time
 * a story is carved out of a shared sheet.
 *
 * Usage:  node tools/split-css.mjs <in.css> <core.css> <story.css>
 *
 * Known correction after the first run: a comment sitting BETWEEN two selectors
 * in a list was being comma-split into fake selectors, which destroyed the
 * reduced-motion rule in both outputs. `selectorList` strips comments now; the
 * two damaged rules were repaired by hand.
 */
import { readFileSync, writeFileSync } from "node:fs";

// Class BLOCKS (the part before `__`/`--`) that belong to the flagship story.
// Everything not listed is core. Erring toward core would leave a story-only
// rule in the shared sheet; erring toward story would leave a core component
// unstyled when no plugin loads -- so the list is explicit either way.
const STORY_BLOCKS = new Set([
  // the companion column
  "assistant", "companion", "bubble", "formchip", "formchips", "formtrack",
  // the character sheet
  "sheet", "statline", "wounds", "satchel",
  // dice
  "dice", "roll", "rolls",
  // encounters
  "encounter", "approach", "resolve",
  // journal / codex / barter
  "journal", "quest", "quests",
  "codexcard", "codexgrid", "codextab", "codextabs", "roads", "plate",
  "barter", "beam", "seal", "offer",
  // the pack and crafting
  "pack", "packactions", "packdetail", "packgrid", "packitem", "packtab",
  "packtabs", "inventory", "ingredient", "ingredients", "recipe", "recipes",
  "thing", "things", "tagchip",
  // the four-phase furniture and the masthead gear
  "phaseband", "phasepill", "chromebar", "gear",
]);

// Exact class names that override the block default.
const EXACT_STORY = new Set(["meter--trust"]);
const EXACT_CORE = new Set([]);

const [, , inPath, corePath, storyPath] = process.argv;
const src = readFileSync(inPath, "utf8");

/** Split a source string into top-level nodes, preserving order and text. */
function nodes(text) {
  const out = [];
  let i = 0;
  while (i < text.length) {
    // whitespace + comments pass through as filler attached to the next node
    if (text.startsWith("/*", i)) {
      const end = text.indexOf("*/", i + 2);
      const stop = end === -1 ? text.length : end + 2;
      out.push({ kind: "comment", text: text.slice(i, stop) });
      i = stop;
      continue;
    }
    if (/\s/.test(text[i])) {
      let j = i;
      while (j < text.length && /\s/.test(text[j])) j += 1;
      out.push({ kind: "space", text: text.slice(i, j) });
      i = j;
      continue;
    }
    // a rule or at-rule: read the prelude up to `{` or `;`
    let j = i;
    while (j < text.length && text[j] !== "{" && text[j] !== ";") {
      if (text.startsWith("/*", j)) {
        const end = text.indexOf("*/", j + 2);
        j = end === -1 ? text.length : end + 2;
        continue;
      }
      j += 1;
    }
    if (text[j] === ";") {
      out.push({ kind: "statement", text: text.slice(i, j + 1) });
      i = j + 1;
      continue;
    }
    const prelude = text.slice(i, j);
    // balanced brace scan for the body
    let depth = 0;
    let k = j;
    for (; k < text.length; k += 1) {
      if (text.startsWith("/*", k)) {
        const end = text.indexOf("*/", k + 2);
        k = end === -1 ? text.length : end + 1;
        continue;
      }
      if (text[k] === "{") depth += 1;
      else if (text[k] === "}") {
        depth -= 1;
        if (depth === 0) break;
      }
    }
    out.push({
      kind: "block",
      prelude,
      body: text.slice(j + 1, k),
      text: text.slice(i, k + 1),
    });
    i = k + 1;
  }
  return out;
}

/** Which side a single selector belongs to. */
function sideOfSelector(sel) {
  const classes = sel.match(/\.[a-zA-Z_][a-zA-Z0-9_-]*/g) || [];
  for (const raw of classes) {
    const name = raw.slice(1);
    if (EXACT_STORY.has(name)) return "story";
    if (EXACT_CORE.has(name)) return "core";
  }
  for (const raw of classes) {
    const block = raw.slice(1).split("__")[0].split("--")[0];
    if (STORY_BLOCKS.has(block)) return "story";
  }
  return "core";
}

/** Split a comma-separated selector list, ignoring commas inside (). */
function selectorList(raw) {
  // Comments are legal BETWEEN selectors and the reduced-motion block uses one
  // that way. Left in, the comment body gets comma-split into fake selectors
  // and the rule is destroyed -- which is exactly what happened on the first
  // run, so it is asserted against below rather than only fixed.
  const prelude = raw.replace(/\/\*[\s\S]*?\*\//g, " ");
  const parts = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < prelude.length; i += 1) {
    const c = prelude[i];
    if (c === "(" || c === "[") depth += 1;
    else if (c === ")" || c === "]") depth -= 1;
    else if (c === "," && depth === 0) {
      parts.push(prelude.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(prelude.slice(start));
  return parts.map((p) => p.trim()).filter(Boolean);
}

const buckets = { core: [], story: [] };
let dropped = 0;

function emitRule(node, target) {
  const sels = selectorList(node.prelude);
  const groups = { core: [], story: [] };
  for (const sel of sels) groups[sideOfSelector(sel)].push(sel);

  for (const side of ["core", "story"]) {
    if (!groups[side].length) continue;
    target[side].push(`${groups[side].join(",\n")} {${node.body}}`);
  }
  if (!sels.length) dropped += 1;
}

function walk(list, target) {
  let pending = "";
  for (const node of list) {
    if (node.kind === "space") {
      pending += node.text.includes("\n\n") ? "\n\n" : "\n";
      continue;
    }
    if (node.kind === "comment") {
      // Comments ride with whichever rule follows. Buffering them means an
      // orphaned trailing comment is dropped rather than duplicated -- that is
      // deliberate; a comment is not a declaration.
      pending += node.text + "\n";
      continue;
    }
    if (node.kind === "statement") {
      // @import / @charset -- these are rewritten by hand in the new entry.
      pending = "";
      continue;
    }
    const at = node.prelude.trim().startsWith("@");
    if (at) {
      const name = node.prelude.trim().split(/[\s({]/)[0];
      if (name === "@media" || name === "@supports" || name === "@container") {
        const inner = { core: [], story: [] };
        walk(nodes(node.body), inner);
        for (const side of ["core", "story"]) {
          if (!inner[side].length) continue;
          const inside = inner[side].join("\n\n").replace(/^/gm, "  ");
          target[side].push(`${pending}${node.prelude.trim()} {\n${inside}\n}`);
        }
        pending = "";
        continue;
      }
      // @keyframes / @font-face / @property are atomic. Keyframes named after a
      // story animation still have to be reachable from core if core uses them,
      // so they all go to core: an unused keyframe costs nothing, a missing one
      // silently kills an animation.
      target.core.push(pending + node.text);
      pending = "";
      continue;
    }
    const sels = selectorList(node.prelude);
    const groups = { core: [], story: [] };
    for (const sel of sels) groups[sideOfSelector(sel)].push(sel);
    for (const side of ["core", "story"]) {
      if (!groups[side].length) continue;
      target[side].push(`${pending}${groups[side].join(",\n")} {${node.body}}`);
    }
    if (!sels.length) dropped += 1;
    pending = "";
  }
}

walk(nodes(src), buckets);

writeFileSync(corePath, buckets.core.join("\n\n") + "\n", "utf8");
writeFileSync(storyPath, buckets.story.join("\n\n") + "\n", "utf8");

// ---- reporting -----------------------------------------------------------
const declCount = (t) => (t.match(/;/g) || []).length;
console.log(`in   : ${src.length} bytes, ${declCount(src)} semicolons`);
console.log(`core : ${buckets.core.length} rules`);
console.log(`story: ${buckets.story.length} rules`);
console.log(`dropped preludes: ${dropped}`);

// Selectors landing on BOTH sides are the only way this split can change the
// cascade (core loads first, story second, so a story rule now wins a tie it
// used to lose). Print them so they can be checked by hand.
function selSet(rules) {
  const set = new Set();
  for (const r of rules) {
    for (const s of selectorList(r.slice(r.lastIndexOf("}\n") + 1).split("{")[0])) set.add(s);
  }
  return set;
}
const a = selSet(buckets.core);
const b = selSet(buckets.story);
const both = [...a].filter((s) => b.has(s));
console.log(`selectors on both sides: ${both.length}`, both.slice(0, 20));

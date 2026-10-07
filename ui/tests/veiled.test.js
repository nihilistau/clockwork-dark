/**
 * THE VEILED RULE, held on the client side of the wire.
 *
 * A `hidden` value never leaves the server, so there is nothing here to leak.
 * A `veiled` value arrives as a BAND STRING with no number attached -- that is
 * the shape of the row, and the shape IS the permission. Which means the client
 * cannot reveal the number; it can only MANUFACTURE one, by looking the band up
 * in a threshold table, or by turning its ordinal into a width, a percentage or
 * a tooltip. The moment it does, the design rule is dead even though the
 * integer never crossed the wire.
 *
 * `tests/test_ui_contract.py` guards one instance of this (the Garden's
 * `closeness`) by reading source as text. This holds the general rule two ways:
 * it RENDERS the components and looks at what came out, and it reads every
 * story plugin for the arithmetic that would break it.
 *
 * Rendering happens through `react-dom/server`, which needs no DOM -- so the
 * suite still runs in node and this file is not the reason to add jsdom.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath, URL } from "node:url";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Meter } from "../src/core/parts/Meters.jsx";
import { FileChip, HeatLadder } from "../src/stories/neon-city/parts/Ladder.jsx";

const html = (element) => renderToStaticMarkup(element);

const STORIES = fileURLToPath(new URL("./../src/stories/", import.meta.url));
const PANELS_DIR = fileURLToPath(new URL("./../src/core/panels/", import.meta.url));

describe("core's generic meter", () => {
  it("draws a veiled row as a word, with no width and no percentage", () => {
    const out = html(
      React.createElement(Meter, {
        row: { name: "heat", label: "Heat", kind: "meter", band: "some" },
      })
    );
    expect(out).toContain("some");
    // The two ways a band becomes a number in the markup.
    expect(out).not.toMatch(/width:/);
    expect(out).not.toContain("%");
    // And the ARIA surface must not carry one either -- a value read aloud is
    // still a value.
    expect(out).not.toMatch(/aria-valuenow/);
  });

  it("draws a public row as a real track, because that one IS a number", () => {
    const out = html(
      React.createElement(Meter, {
        row: { name: "hp", label: "Condition", kind: "meter", value: 12, min: 0, max: 20 },
      })
    );
    expect(out).toMatch(/width:\s*60%/);
    expect(out).toContain('aria-valuenow="12"');
  });
});

describe("the heat ladder", () => {
  it("substitutes one word for another and prints no figure", () => {
    const out = html(React.createElement(HeatLadder, { band: "some" }));
    expect(out).toContain("WANTED");
    // The bible's thresholds are 0 / 20 / 45 / 70 / 90. None of them, nor any
    // other digit, may appear: this is the component with the table in reach.
    expect(out).not.toMatch(/\d/);
    expect(out).not.toContain("%");
    expect(out).not.toMatch(/style=/);
  });

  it("lights the rungs up to the band and no further", () => {
    const out = html(React.createElement(HeatLadder, { band: "faint" }));
    // Two lit of five: the same disclosure core's own glyph row makes, and it
    // carries no scale to measure against.
    expect(out.match(/is-lit/g)).toHaveLength(2);
  });

  it("reads an unknown band as UNREAD, never as the safe end", () => {
    // A payload with no heat row must not tell the runner they are clean. This
    // is the failure that matters: silence rendered as safety.
    for (const band of [undefined, null, "", "nonsense"]) {
      const out = html(React.createElement(HeatLadder, { band }));
      expect(out).toContain("UNREAD");
      expect(out).not.toContain("CLEAN");
    }
  });

  it("covers every band the engine can send", () => {
    // engine/state/schema.py::VEILED_BANDS. A band with no rung would render
    // as UNREAD on a live run, which would read as an outage rather than as
    // heat.
    const rungs = ["none", "faint", "some", "strong", "utmost"].map((band) =>
      html(React.createElement(HeatLadder, { band }))
    );
    for (const out of rungs) expect(out).not.toContain("UNREAD");
    expect(rungs[0]).toContain("CLEAN");
    expect(rungs[4]).toContain("BURNED");
  });
});

describe("the file", () => {
  it("says the forecast's confidence and never a countdown", () => {
    const out = html(React.createElement(FileChip, { band: "strong" }));
    expect(out).toContain("CONVERGING");
    // "14 days left" is the sentence state.yaml forbids.
    expect(out).not.toMatch(/\d/);
    expect(out.toLowerCase()).not.toContain("day");
  });

  it("covers every band, and an absent one is UNREAD", () => {
    for (const [band, word] of [
      ["none", "FILED"],
      ["faint", "HOLDING"],
      ["some", "FIRMING"],
      ["strong", "CONVERGING"],
      ["utmost", "DUE"],
    ]) {
      expect(html(React.createElement(FileChip, { band }))).toContain(word);
    }
    expect(html(React.createElement(FileChip, { band: undefined }))).toContain("UNREAD");
  });
});

/** Every .jsx/.js under `dir`, with comments stripped: [[name, code], ...]. */
function sources(dir) {
  const out = [];
  const walk = (at) => {
    for (const entry of readdirSync(at, { withFileTypes: true })) {
      const path = join(at, entry.name);
      if (entry.isDirectory()) {
        walk(path);
        continue;
      }
      if (!/\.jsx?$/.test(entry.name)) continue;
      const raw = readFileSync(path, "utf8");
      const code = raw
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/^\s*\/\/.*$/gm, "");
      out.push([path.slice(dir.length).replace(/\\/g, "/"), code]);
    }
  };
  walk(dir);
  return out;
}

describe("no story does arithmetic on a band", () => {
  /**
   * Lines that READ a band off the payload.
   *
   * Scoped to `.band` and `closeness` rather than to the bare word `band`, and
   * that is a correctness decision rather than a convenience: the flagship's
   * Codex has a local `band` meaning which woodcut ring a page is bound in,
   * and it does modular arithmetic on it quite properly. A test that flagged
   * that line would be asserting something false about it, and a false
   * assertion in a guard is worse than no guard -- the next author deletes the
   * guard rather than the code.
   *
   * What survives the scoping is the thing that matters: a value that came off
   * the wire as a word, being turned back into a quantity.
   */
  const READS = /[^\n]*(\.band\b|\bcloseness\b)[^\n]*/g;

  it.each(sources(STORIES))("%s", (_name, code) => {
    for (const line of code.match(READS) || []) {
      expect(line, `arithmetic on a band: ${line.trim()}`).not.toMatch(
        /(?<![\w-])(band|closeness)\b\s*[*/+-]|[*/+-]\s*(?<![\w-])(band|closeness)\b/
      );
      expect(line, `a percentage from a band: ${line.trim()}`).not.toContain("%");
      expect(line, `a width from a band: ${line.trim()}`).not.toContain("width");
    }
  });
});

describe("no core panel does arithmetic on a band", () => {
  // The panels read the payload's words through `scaleIndex`; a line that
  // READS one of those words must not turn it into a number, a percentage or
  // a width. `.clarity`, `.alarm`, `.prep`, `.wanted` and `scaleIndex(` join
  // `.band` and `closeness` (`scaleIndex` anchors the scan: every lookup goes
  // through it, so a line that indexes a scale is a line that is checked).
  const READS = /[^\n]*(\.band\b|\bcloseness\b|\.clarity\b|\.alarm\b|\.prep\b|\.wanted\b|scaleIndex\()[^\n]*/g;
  const WORD = "(band|closeness|clarity|alarm|prep|wanted)";
  // `String.raw`: a plain template literal would turn `\b` into a backspace
  // and `\w` into `w`, and nothing would ever match (T8 review finding 1).
  // The second arm is the index itself: `scaleIndex(...)` beside an operator
  // is arithmetic on a band even when no payload key is named on the line.
  // KNOWN LIMITS: an index kept in a variable and divided on a later line, and
  // a `scaleIndex(f(x), w) * 2` with nested parentheses, pass; `sketchLayers`'
  // own `3 * index` is the spec's formula (§4.1), a layer count, not a width.
  const ARITHMETIC = new RegExp(
    String.raw`(?<![\w-])${WORD}\b\s*[*/+-]|[*/+-]\s*(?<![\w-])${WORD}\b|scaleIndex\([^)]*\)\s*[*/+-]|[*/+-]\s*scaleIndex\(`
  );
  it.each(sources(PANELS_DIR))("%s", (_name, code) => {
    for (const line of code.match(READS) || []) {
      expect(line, `arithmetic on a band: ${line.trim()}`).not.toMatch(ARITHMETIC);
      expect(line, `a percentage: ${line.trim()}`).not.toContain("%");
      expect(line, `a width: ${line.trim()}`).not.toContain("width");
    }
  });
});

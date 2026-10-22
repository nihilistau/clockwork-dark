/**
 * Writes `build-source.txt` into the built dist: a hash of the build's inputs.
 *
 * WHY. tests/test_ui_contract.py asks whether the committed dist is current.
 * Comparing git history cannot be satisfied by a change a rebuild leaves
 * byte-identical (a comment in src): there is nothing to commit, so the guard
 * stays red. A hash of the inputs, written by the build and compared with the
 * hash of the committed inputs, can: a rebuild always rewrites the marker.
 * It also catches a dist built from source that was stale when it was built.
 *
 * THE CONVENTION (the Python test reimplements it; keep the two equal):
 *   inputs   ui/src (every file), ui/vite.config.js, ui/package.json,
 *            ui/index.html -- the guard's BUILD_INPUTS.
 *   per file `<repo-relative posix path>\n<sha256 hex of its bytes with every
 *            CRLF turned into LF>\n`; files sorted by path (code points).
 *   package.json is first reduced to its bundle-relevant keys: `version`,
 *            `scripts.screenshots` and `devDependencies.playwright-core` are
 *            dropped (they never reach the bundle), then it is written as
 *            canonical JSON (sorted keys, no spaces, no escaping of non-ASCII).
 *   marker   sha256 hex of the concatenated lines, then a newline.
 */
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

export const MARKER = "build-source.txt";

export const BUNDLE_NEUTRAL = [
  ["version"],
  ["scripts", "screenshots"],
  ["devDependencies", "playwright-core"],
];

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

/** Bytes with CRLF turned into LF, so Windows and Linux checkouts agree. */
export function normalise(bytes) {
  const out = [];
  for (let i = 0; i < bytes.length; i++) {
    if (bytes[i] === 0x0d && bytes[i + 1] === 0x0a) continue;
    out.push(bytes[i]);
  }
  return Buffer.from(out);
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const keys = Object.keys(value).sort();
    return `{${keys.map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

/** package.json reduced to what reaches the bundle, as canonical JSON bytes. */
export function packageBytes(bytes) {
  const tree = JSON.parse(bytes.toString("utf8"));
  for (const path of BUNDLE_NEUTRAL) {
    let node = tree;
    for (const key of path.slice(0, -1)) node = node && typeof node === "object" ? node[key] : undefined;
    if (node && typeof node === "object") delete node[path.at(-1)];
  }
  return Buffer.from(canonical(tree), "utf8");
}

/** `entries` is [{ path: "ui/src/x.js", bytes: Buffer }]; order does not matter. */
export function hashInputs(entries) {
  const lines = entries
    .map(({ path, bytes }) => ({
      path,
      bytes: path === "ui/package.json" ? packageBytes(bytes) : normalise(bytes),
    }))
    .sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0))
    .map(({ path, bytes }) => `${path}\n${sha256(bytes)}\n`);
  return sha256(Buffer.from(lines.join(""), "utf8"));
}

function walk(dir, out) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
}

export function readInputs(uiDir) {
  const files = [];
  walk(join(uiDir, "src"), files);
  for (const name of ["vite.config.js", "package.json", "index.html"]) files.push(join(uiDir, name));
  return files.map((file) => ({
    path: `ui/${relative(uiDir, file).split(sep).join("/")}`,
    bytes: readFileSync(file),
  }));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const uiDir = fileURLToPath(new URL("..", import.meta.url));
  const dist = join(uiDir, "..", "content", "scenes", "clockwork", "static", "dist");
  writeFileSync(join(dist, MARKER), `${hashInputs(readInputs(uiDir))}\n`);
}

import { describe, expect, it } from "vitest";

import { hashInputs } from "../tools/build-source-hash.mjs";

const file = (path, text) => ({ path, bytes: Buffer.from(text, "utf8") });
const PKG = (extra = {}) =>
  file("ui/package.json", JSON.stringify({ version: "1.0.0", dependencies: { react: "^18" }, ...extra }));

describe("build-source hash", () => {
  const base = [file("ui/src/a.js", "one\ntwo\n"), file("ui/src/b.js", "x\n"), PKG()];

  it("is the same whatever order the inputs arrive in", () => {
    expect(hashInputs([...base].reverse())).toBe(hashInputs(base));
  });

  it("treats CRLF and LF alike", () => {
    const crlf = [file("ui/src/a.js", "one\r\ntwo\r\n"), base[1], base[2]];
    expect(hashInputs(crlf)).toBe(hashInputs(base));
  });

  it("changes when only a comment changes", () => {
    const commented = [file("ui/src/a.js", "one\n// note\ntwo\n"), base[1], base[2]];
    expect(hashInputs(commented)).not.toBe(hashInputs(base));
  });

  it("changes when a file is added or renamed", () => {
    expect(hashInputs([...base, file("ui/src/c.js", "")])).not.toBe(hashInputs(base));
    expect(hashInputs([file("ui/src/z.js", "one\ntwo\n"), base[1], base[2]])).not.toBe(hashInputs(base));
  });

  it("ignores package.json's bundle-neutral keys and judges the rest", () => {
    const bumped = [base[0], base[1], file("ui/package.json", JSON.stringify({ dependencies: { react: "^18" }, version: "9.9.9" }))];
    expect(hashInputs(bumped)).toBe(hashInputs(base));
    const dep = [base[0], base[1], PKG({ dependencies: { react: "^19" } })];
    expect(hashInputs(dep)).not.toBe(hashInputs(base));
  });
});

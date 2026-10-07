// @vitest-environment jsdom
/**
 * Settings when they cannot be written (v0.21.0, spec §7, F8).
 *
 * Hosted mode answers `GET /api/settings` with `writable: false` and no
 * `config_path` (a path on the operator's machine). The panel used to render
 * an empty `<code>` where the path stood, and Apply/Reset buttons the server
 * refuses. Local mode's shape (no `writable` key) is unchanged.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Settings, { DEFAULTS } from "../src/core/screens/Settings.jsx";

const ROW = { key: "world.evil_base_rate_per_day", label: "Pace", group: "World", type: "float", min: 0, max: 1, step: 0.01, value: 0.2 };

let host;
let root;
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  React.act(() => root.unmount());
  host.remove();
});

async function open(spec) {
  globalThis.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => spec }));
  await React.act(async () => root.render(<Settings prefs={DEFAULTS} onChange={() => {}} onClose={() => {}} />));
}

const buttons = () => [...document.querySelectorAll("button")].map((b) => b.textContent);

describe("Settings when they cannot be written (F8)", () => {
  it("hosted: no path row, no Apply or Reset, engine fields read-only, preferences live", async () => {
    await open({ settings: [ROW], groups: ["World"], writable: false });
    expect(document.querySelector(".settings__footnote code")).toBeNull();
    expect(document.querySelector(".settings__footnote").textContent).toBe("These are set by the operator of this server.");
    expect(buttons().some((t) => t.startsWith("Apply") || t === "Applied")).toBe(false);
    expect(buttons()).not.toContain("Reset to defaults");
    expect(document.getElementById("set-world-evil_base_rate_per_day").disabled).toBe(true);
    const motion = [...document.querySelectorAll('input[type="checkbox"]')][0];
    expect(motion.disabled).toBe(false);
  });

  it("local: both buttons and the path", async () => {
    await open({ settings: [ROW], groups: ["World"], config_path: "config/local.yaml" });
    expect(document.querySelector(".settings__footnote code").textContent).toBe("config/local.yaml");
    expect(buttons()).toContain("Reset to defaults");
    expect(buttons()).toContain("Applied");
    expect(document.getElementById("set-world-evil_base_rate_per_day").disabled).toBe(false);
  });
});

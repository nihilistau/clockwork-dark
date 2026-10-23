// ui/tests/helpers/dom.js -- the repo's way (createRoot + React.act, ui/tests/job-panel.test.jsx),
// shared by the phone tests (v0.22.0). Import it only from a file whose first line is
// `// @vitest-environment jsdom`.
import React from "react";
import { createRoot } from "react-dom/client";

/** A fresh host and root: `render(node)`, `unmount()`. Call unmount in afterEach. */
export function mount() {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  return {
    host,
    render: (node) => React.act(() => root.render(node)),
    renderAsync: (node) => React.act(async () => { root.render(node); }),
    unmount: () => {
      React.act(() => root.unmount());
      host.remove();
    },
  };
}

export const click = (el) => React.act(() => el.click());

/** A keydown on `target` (window by default), as choice-row.test.jsx dispatches it. */
export const key = (k, target = window) =>
  React.act(() => target.dispatchEvent(new window.KeyboardEvent("keydown", { key: k, bubbles: true })));

/** A pointer event by type ("pointerdown" | "pointermove" | "pointerup"); jsdom has no PointerEvent, and
 *  React listens by event type, so a MouseEvent of that type reaches onPointerDown and friends. */
export const pointer = (el, type, clientX) =>
  React.act(() => el.dispatchEvent(new window.MouseEvent(type, { clientX, bubbles: true })));

/** Type into a controlled input or textarea: React's value tracker needs the native setter. */
export function typeInto(input, value) {
  const proto = input.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
  React.act(() => {
    setter.call(input, value);
    input.dispatchEvent(new window.Event("input", { bubbles: true }));
  });
}

/** The first button whose aria-label or text matches `name` (a RegExp or a string), else null. */
export function button(host, name) {
  const test = name instanceof RegExp ? (s) => name.test(s) : (s) => s === name;
  return [...host.querySelectorAll("button")].find((b) => test(b.getAttribute("aria-label") || b.textContent || "")) || null;
}

export const byTestId = (host, id) => host.querySelector(`[data-testid="${id}"]`);
export const byText = (host, text) =>
  [...host.querySelectorAll("*")].find((el) => el.children.length === 0 && el.textContent === text) || null;

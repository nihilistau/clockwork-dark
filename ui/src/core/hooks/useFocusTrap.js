/**
 * Modal focus management.
 *
 * Every overlay in the old client was a plain <div role="dialog">: Tab walked
 * straight out of it into the play screen behind, Esc did nothing, and closing
 * dropped focus back on <body> so a keyboard player lost their place entirely.
 * This hook is the one implementation of all three behaviours.
 *
 * The listeners sit on `document`, not on the dialog element. A listener bound
 * to the container only sees keys pressed while focus is already inside it —
 * and focus leaves the moment the player clicks the backdrop, at which point
 * Esc silently stops working and the dialog cannot be dismissed by keyboard at
 * all. Handling it at the document lets us also pull stray focus back in.
 */
import { useEffect, useRef } from "react";

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

// Innermost-first stack of open traps. A cutscene can start while the codex
// is open; with document-level listeners both would answer one Esc and two
// dialogs would vanish for one keypress.
const stack = [];

export default function useFocusTrap(onClose) {
  const ref = useRef(null);
  // Held in a ref, not a dependency. Callers pass an inline arrow, so a
  // dependency would re-run the effect on every render -- which would yank
  // focus back to the first control the moment you changed anything inside
  // the dialog, and re-capture "where to return to" as somewhere inside it.
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    const container = ref.current;
    if (!container) return undefined;

    // Captured BEFORE we move focus, so closing returns the player to the
    // control that opened the dialog rather than to the top of the document.
    const returnTo = document.activeElement;

    stack.push(container);

    const focusable = () => Array.from(container.querySelectorAll(FOCUSABLE));
    (focusable()[0] || container).focus();

    function onKey(event) {
      // Only the topmost dialog answers.
      if (stack[stack.length - 1] !== container) return;
      if (event.key === "Escape") {
        event.preventDefault();
        close.current?.();
        return;
      }
      if (event.key !== "Tab") return;

      const items = focusable();
      if (items.length === 0) {
        event.preventDefault();
        container.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];

      // Focus wandered out (a backdrop click parks it on <body>). Tab brings
      // it home rather than starting a walk through the page behind.
      if (!container.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
        return;
      }
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      const at = stack.indexOf(container);
      if (at !== -1) stack.splice(at, 1);
      if (returnTo && typeof returnTo.focus === "function") returnTo.focus();
    };
    // Mount/unmount only -- see the ref above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return ref;
}

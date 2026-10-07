/**
 * Keys 1-9 press the first nine items (the choice row's binding, shared with
 * the approaches when they are the only moves: two lists never bind one key).
 * Never steals a digit typed into a field, never with a modifier held.
 */
import { useEffect } from "react";

export function useDigitKeys(items, onPick, enabled) {
  useEffect(() => {
    if (!enabled || !items || items.length === 0) return undefined;
    function onKey(event) {
      const tag = event.target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || event.target?.isContentEditable) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const index = Number(event.key) - 1;
      if (Number.isInteger(index) && index >= 0 && index < Math.min(items.length, 9)) {
        event.preventDefault();
        onPick(items[index]);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, onPick, enabled]);
}

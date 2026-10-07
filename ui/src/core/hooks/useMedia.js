/**
 * A media query, live. `matchMedia` is read once on mount and followed on
 * change; a host without it (a test, an old browser) answers false.
 */
import { useEffect, useState } from "react";

export const NARROW_QUERY = "(max-width: 900px)";
export const COARSE_QUERY = "(pointer: coarse)";
/** A short window (under 820px tall): the play column's height budget is tight (K2). */
export const SHORT_QUERY = "(max-height: 819.98px)";

function query(text) {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(text)
    : null;
}

export function useMedia(text) {
  const [matches, setMatches] = useState(() => Boolean(query(text)?.matches));
  useEffect(() => {
    const list = query(text);
    if (!list) return undefined;
    const on = () => setMatches(list.matches);
    on();
    list.addEventListener?.("change", on);
    return () => list.removeEventListener?.("change", on);
  }, [text]);
  return matches;
}

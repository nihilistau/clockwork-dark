/**
 * Where a word sits in its scale, low to high (spec §4.1, §4.2): -1 when it is
 * not there (an out-of-scale word, or "" below the first threshold).
 *
 * THE VEILED RULE. The index lights marks and picks a sketch layer. It is never
 * printed, never turned into a percentage or a width -- the scale is the
 * story's own words, ordered, and that is all that crosses the wire.
 */
export function scaleIndex(scale, word) {
  if (!Array.isArray(scale) || !word) return -1;
  return scale.indexOf(word);
}

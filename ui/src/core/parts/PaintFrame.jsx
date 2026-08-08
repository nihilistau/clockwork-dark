/**
 * The painted frame. One implementation, three sizes.
 *
 * A stack of layers over a caller-supplied wash: candle bloom, low mist band,
 * volumetric ray, an optional corruption bleed, grain, a tuned vignette, a film
 * lip, a watermark and a caption. It knows nothing about what is being painted
 * -- the wash, the tint and the copy all arrive as props -- which is why it
 * sits in core while the flagship's twenty-place wash table sits in its story.
 *
 * `size` picks the vignette tuning. The old `.plate__vignette` copied the 320px
 * hero's `inset 0 0 70px 14px` onto a 169px codex tile, where a 70px blur plus
 * 14px spread covers the entire tile -- it would have blacked out real art, and
 * it did black out the blank. The vignette is a variable now, not a constant
 * that happens to suit one box.
 */
import React from "react";

export default function PaintFrame({
  wash,
  tint,
  size = "hero",
  corrupted = false,
  caption,
  watermark,
  className = "",
  style,
  children,
}) {
  return (
    <div className={`paint paint--${size} ${className}`} style={style}>
      <span className="paint__wash" style={{ background: wash }} aria-hidden="true" />
      {children}
      {tint && <span className="paint__tint" style={{ background: tint }} aria-hidden="true" />}
      <span className="paint__mist" aria-hidden="true" />
      <span className="paint__ray" aria-hidden="true" />
      {corrupted && <span className="paint__rot" aria-hidden="true" />}
      <span className="paint__grain" aria-hidden="true" />
      <span className="paint__vignette" aria-hidden="true" />
      <span className="paint__lip" aria-hidden="true" />
      {watermark && <span className="paint__mark">{watermark}</span>}
      {caption && <span className="paint__caption">{caption}</span>}
    </div>
  );
}

// Named export too: several call sites already say `{ PaintFrame }`.
export { PaintFrame };

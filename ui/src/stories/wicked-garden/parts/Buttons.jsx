/**
 * PetalButton and WaxSealButton, plus the implication whisper.
 *
 * WHY THESE ARE DRAWN AND NOT PHOTOGRAPHED
 * ----------------------------------------
 * `concept/ui-kit/buttons/` holds nine JPEGs of both controls in every state.
 * They are not usable yet and the kit's own README says so: the backgrounds are
 * `#00FF00` chroma, to be keyed before ship, and only the icon exports have
 * been taken to alpha. Dropping a green-backed JPEG in would look broken and
 * would also bake a raster into a control that has to stretch to its label.
 *
 * So the geometry is taken from the vector sheet, which has no key in it:
 * `concept/ui-kit/svg/wg-ui-kit.svg`. The petal is an ellipse rx=68 ry=32; the
 * seal is r=36 with an inner ring at r=18. Those numbers are the tokens below.
 * When the rasters are keyed, `background-image` replaces the gradients and
 * nothing else about these files changes.
 *
 * STATE MATRIX
 * ------------
 * 09-UI-COMPONENT-KIT requires default / hover / pressed / focused / disabled
 * on every interactive control, and says a danger action "adds danger emphasis
 * without changing hit geometry". There is art for three of the five, so focus
 * and disabled are derived; danger is a palette, not a different shape.
 *
 * The hit box is a RECTANGLE over the ellipse (`hit_box: rect_over_ellipse`)
 * with a 48dp minimum, which is why the petal's padding is set from a min-height
 * rather than from the ellipse.
 */
import React from "react";

/**
 * A choice, with the consequence said out loud underneath it.
 *
 * "Implication whispers (default ON for accessibility of consequence)" --
 * 06-UI-UX. They are a second line on the chip, not a tooltip, because a
 * consequence a player can only discover by hovering is not accessible. The
 * rule that keeps them honest: never name an ending id. "She will like this"
 * and "This spends the Briar Key" are the register; "leads to E3b" is not.
 */
export function PetalButton({
  children,
  whisper,
  showWhisper = true,
  tone = "default",
  disabled = false,
  onClick,
  ...rest
}) {
  return (
    <button
      type="button"
      className="petal"
      data-tone={tone}
      disabled={disabled}
      onClick={onClick}
      {...rest}
    >
      <span className="petal__label">{children}</span>
      {whisper && showWhisper && (
        <span className="petal__whisper">
          {/* Marked as a note rather than as part of the label: a screen
              reader should read the choice, then its consequence, not one
              run-on sentence. */}
          {whisper}
        </span>
      )}
    </button>
  );
}

// Accept / Renegotiate / Refuse. The art map is nine-slice.json's `buttons.
// wax_seal.actions`: accept and renegotiate share the default seal (the second
// gold-tinted), refuse gets its own. Refuse is COLD SILVER, not red -- this
// story's danger is being made a thing, not being hurt.
const SEAL_LABEL = {
  accept: "Accept",
  renegotiate: "Renegotiate",
  refuse: "Refuse",
};

/**
 * One of the three bargain verbs.
 *
 * Renegotiate is a first-class action and is drawn like one: same seal, same
 * size, same weight as Accept, differing only in tint. A renegotiate rendered
 * as a secondary link would say "this is the polite way to decline", and it is
 * not -- it is the move that changes the terms.
 */
export function WaxSealButton({ action = "accept", label, disabled, onClick, ...rest }) {
  return (
    <button
      type="button"
      className="seal"
      data-action={action}
      disabled={disabled}
      onClick={onClick}
      {...rest}
    >
      <span className="seal__disc" aria-hidden="true">
        <span className="seal__ring" />
      </span>
      <span className="seal__label">{label || SEAL_LABEL[action] || action}</span>
    </button>
  );
}

export default PetalButton;

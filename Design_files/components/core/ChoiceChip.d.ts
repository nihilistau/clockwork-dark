import * as React from "react";

/**
 * A narrative choice pill — the player's 2–4 options each turn,
 * keyboard-selectable 1–4. Tallow fill, iron edge. Disables the
 * instant it's clicked because the turn is in flight.
 */
export interface ChoiceChipProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Optional 1–4 key badge shown at the leading edge. */
  index?: number | string | null;
  disabled?: boolean;
  onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void;
  children?: React.ReactNode;
}

export function ChoiceChip(props: ChoiceChipProps): JSX.Element;

import * as React from "react";

/**
 * The ledger-button: a pressed, candlelit control with an iron edge.
 * Hover deepens warmth; press insets. Used for confirm/send/settings
 * actions — NOT for narrative choices (use ChoiceChip for those).
 */
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Visual weight. @default "primary" */
  variant?: "primary" | "secondary" | "ghost" | "danger";
  /** @default "md" */
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  /** Glyph rendered before the label (e.g. a Lucide icon). */
  iconLeft?: React.ReactNode;
  /** Glyph rendered after the label. */
  iconRight?: React.ReactNode;
  children?: React.ReactNode;
}

export function Button(props: ButtonProps): JSX.Element;

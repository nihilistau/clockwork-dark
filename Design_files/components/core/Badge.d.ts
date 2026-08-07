import * as React from "react";

/**
 * A small tracked-smallcaps marker for the assistant form tag,
 * weather, phase, or item tags. Restrained accent tones only.
 */
export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** @default "neutral" */
  tone?: "neutral" | "candle" | "brass" | "moss" | "danger" | "corruption";
  children?: React.ReactNode;
}

export function Badge(props: BadgeProps): JSX.Element;

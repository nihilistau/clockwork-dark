import * as React from "react";

/**
 * A non-blocking center-screen dice result. Renders the engine's
 * line verbatim in monospace — "d20: 14 + 2 = 16 vs DC 13 — Success" —
 * with the outcome word tinted green (success) or maroon (fail).
 * Dwells ~1.5s then fades; the caller owns mount/timeout.
 */
export interface DiceToastProps extends React.HTMLAttributes<HTMLDivElement> {
  /** The natural d20 roll. */
  roll: number;
  /** Modifier applied. @default 0 */
  modifier?: number;
  /** Difficulty class checked against. */
  dc?: number;
  /** Outcome word, shown verbatim. @default "Success" */
  outcome?: string;
}

export function DiceToast(props: DiceToastProps): JSX.Element;

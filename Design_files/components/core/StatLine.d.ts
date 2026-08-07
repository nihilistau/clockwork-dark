import * as React from "react";

/**
 * A single ledger row — tracked smallcaps label, monospace tabular
 * value, hairline rule beneath. Stack them to build the character
 * sheet (HP, Stamina, Gold, Location) or any stat readout.
 */
export interface StatLineProps extends React.HTMLAttributes<HTMLDivElement> {
  label: React.ReactNode;
  value: React.ReactNode;
  /** Tint the value brass for emphasis. @default false */
  accent?: boolean;
}

export function StatLine(props: StatLineProps): JSX.Element;

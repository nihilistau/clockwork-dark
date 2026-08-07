import * as React from "react";

/**
 * The chrome time readout — monospace, candlelit, on iron. Reads as
 * plain diegetic time ("Day 12 · Evening") until the World Clock is
 * *discovered* in-world, at which point a small gear glyph appears.
 * Never expose hidden mechanics (Awareness) here.
 */
export interface WorldClockProps extends React.HTMLAttributes<HTMLDivElement> {
  day?: number;
  /** Coarse time-of-day word. @default "Morning" */
  time?: string;
  /** Show the gear glyph once the clock is discovered. @default false */
  discovered?: boolean;
}

export function WorldClock(props: WorldClockProps): JSX.Element;

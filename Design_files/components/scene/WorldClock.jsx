import React from "react";

/**
 * WorldClock — the chrome time readout. Monospace, candlelit, on
 * iron. Once the World Clock is *discovered* in-world, a small gear
 * glyph appears (set `discovered`). Until then it reads as plain
 * diegetic time. Format: "Day 12 · Evening".
 */
export function WorldClock({
  day = 1,
  time = "Morning",
  discovered = false,
  style = {},
  ...rest
}) {
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "0.5rem",
        fontFamily: "var(--font-mono)",
        fontSize: "var(--text-sm)",
        color: "var(--text-candlelight)",
        letterSpacing: "0.02em",
        ...style,
      }}
      {...rest}
    >
      {discovered && (
        <span
          aria-hidden="true"
          style={{
            width: "13px",
            height: "13px",
            display: "inline-block",
            borderRadius: "50%",
            border: "1.5px solid var(--rust-300)",
            boxShadow: "inset 0 0 0 2px var(--surface-chrome)",
            position: "relative",
            top: "1px",
          }}
        />
      )}
      <span style={{ fontVariantNumeric: "tabular-nums" }}>
        Day {day} · {time}
      </span>
    </div>
  );
}

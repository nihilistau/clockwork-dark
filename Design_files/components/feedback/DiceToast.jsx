import React from "react";

/**
 * DiceToast — non-blocking center-screen result. Shows the engine's
 * dice line verbatim in mono, with the outcome word tinted by
 * result. Dwells ~1.5s then fades (caller handles timing/mount).
 */
export function DiceToast({
  roll,
  modifier = 0,
  dc,
  outcome = "Success",
  style = {},
  ...rest
}) {
  const total = (Number(roll) || 0) + (Number(modifier) || 0);
  const sign = modifier >= 0 ? "+" : "−";
  const win = String(outcome).toLowerCase().startsWith("s");
  const outColor = win ? "var(--forest-500)" : "var(--blood-quiet)";

  return (
    <div
      role="status"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "0.6rem",
        fontFamily: "var(--font-mono)",
        fontSize: "var(--text-md)",
        background: "var(--surface-chrome)",
        color: "var(--text-on-dark)",
        border: "var(--border-rule) solid var(--accent-brass)",
        borderRadius: "var(--radius-sm)",
        padding: "0.7rem 1.1rem",
        boxShadow: "var(--shadow-raise)",
        ...style,
      }}
      {...rest}
    >
      <span style={{ color: "var(--text-candlelight)" }}>d20:</span>
      <span style={{ fontVariantNumeric: "tabular-nums" }}>
        {roll} {sign} {Math.abs(modifier)} = {total}
      </span>
      {dc != null && (
        <span style={{ color: "var(--text-muted)" }}>vs DC {dc}</span>
      )}
      <span style={{ color: outColor, fontWeight: "var(--weight-semibold)" }}>
        — {outcome}
      </span>
    </div>
  );
}

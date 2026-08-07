import React from "react";

/**
 * StatLine — a single ledger row: tracked label left, monospace
 * tabular value right, hairline rule between. The character sheet
 * is a stack of these.
 */
export function StatLine({ label, value, accent = false, style = {}, ...rest }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "baseline",
        gap: "0.75rem",
        padding: "0.3rem 0",
        borderBottom: "var(--border-hair) solid var(--line-soft)",
        ...style,
      }}
      {...rest}
    >
      <span
        style={{
          fontFamily: "var(--font-ui)",
          fontSize: "var(--text-xs)",
          textTransform: "uppercase",
          letterSpacing: "var(--tracking-label)",
          color: "var(--text-muted)",
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: "var(--text-sm)",
          fontWeight: "var(--weight-medium)",
          fontVariantNumeric: "tabular-nums",
          color: accent ? "var(--rust-clock)" : "var(--text-body)",
        }}
      >
        {value}
      </span>
    </div>
  );
}

import React from "react";

/**
 * Badge — a small tracked-smallcaps marker. Tones map to the
 * brand's restrained accent vocabulary. Used for the assistant
 * form tag, weather, phase, item tags.
 */
export function Badge({ tone = "neutral", style = {}, children, ...rest }) {
  const tones = {
    neutral: { bg: "transparent", fg: "var(--text-muted)", bd: "var(--iron-300)" },
    candle: { bg: "rgba(232,196,122,0.18)", fg: "var(--rust-700)", bd: "var(--tallow-700)" },
    brass: { bg: "transparent", fg: "var(--rust-clock)", bd: "var(--rust-clock)" },
    moss: { bg: "rgba(107,127,94,0.18)", fg: "var(--forest-700)", bd: "var(--moss-600)" },
    danger: { bg: "rgba(107,45,45,0.14)", fg: "var(--blood-quiet)", bd: "var(--blood-quiet)" },
    corruption: { bg: "rgba(122,158,79,0.16)", fg: "#52662f", bd: "var(--corruption)" },
  };
  const t = tones[tone] || tones.neutral;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "0.3rem",
        fontFamily: "var(--font-ui)",
        fontSize: "var(--text-xs)",
        fontWeight: "var(--weight-semibold)",
        textTransform: "uppercase",
        letterSpacing: "var(--tracking-label)",
        color: t.fg,
        background: t.bg,
        border: `1px solid ${t.bd}`,
        borderRadius: "var(--radius-sm)",
        padding: "0.12rem 0.42rem",
        lineHeight: 1.5,
        ...style,
      }}
      {...rest}
    >
      {children}
    </span>
  );
}

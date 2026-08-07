import React from "react";

/**
 * ScenePanel — a journal column surface (assistant / sheet). Tracked
 * smallcaps heading, optional iron edge on one side, paper-calm fill.
 * `surface` chooses the fill; `edge` places the 2px ledger rule.
 */
export function ScenePanel({
  title = null,
  surface = "ledger",
  edge = "none",
  style = {},
  children,
  ...rest
}) {
  const surfaces = {
    ledger: "var(--surface-ledger)",
    panel: "var(--surface-panel)",
    narrative: "var(--surface-narrative)",
    card: "var(--surface-card)",
  };
  const edges = {
    none: {},
    left: { borderLeft: "var(--border-rule) solid var(--iron-700)" },
    right: { borderRight: "var(--border-rule) solid var(--iron-700)" },
  };
  return (
    <section
      style={{
        background: surfaces[surface] || surfaces.ledger,
        padding: "var(--space-4)",
        minHeight: 0,
        ...edges[edge],
        ...style,
      }}
      {...rest}
    >
      {title && (
        <h2
          style={{
            margin: "0 0 var(--space-3)",
            fontFamily: "var(--font-ui)",
            fontSize: "var(--text-xs)",
            fontWeight: "var(--weight-semibold)",
            textTransform: "uppercase",
            letterSpacing: "var(--tracking-label)",
            color: "var(--text-body)",
          }}
        >
          {title}
        </h2>
      )}
      {children}
    </section>
  );
}

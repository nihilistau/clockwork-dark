import React from "react";

/**
 * Button — the ledger-button. A pressed, candlelit control with
 * an iron edge. Hover deepens warmth; press insets. No scale tricks.
 */
export function Button({
  variant = "primary",
  size = "md",
  disabled = false,
  type = "button",
  iconLeft = null,
  iconRight = null,
  style = {},
  children,
  ...rest
}) {
  const sizes = {
    sm: { padding: "0.35rem 0.7rem", font: "var(--text-sm)" },
    md: { padding: "0.5rem 0.95rem", font: "var(--text-base)" },
    lg: { padding: "0.65rem 1.25rem", font: "var(--text-md)" },
  };

  const variants = {
    primary: {
      background: "var(--accent-candle)",
      color: "var(--iron-900)",
      border: "var(--border-rule) solid var(--iron-700)",
    },
    secondary: {
      background: "var(--surface-card)",
      color: "var(--text-body)",
      border: "var(--border-rule) solid var(--iron-700)",
    },
    ghost: {
      background: "transparent",
      color: "var(--text-on-dark)",
      border: "var(--border-hair) solid var(--accent-candle)",
    },
    danger: {
      background: "var(--status-danger)",
      color: "var(--linen-100)",
      border: "var(--border-rule) solid var(--iron-900)",
    },
  };

  const s = sizes[size] || sizes.md;
  const v = variants[variant] || variants.primary;

  return (
    <button
      type={type}
      disabled={disabled}
      data-variant={variant}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "0.4rem",
        fontFamily: "var(--font-ui)",
        fontWeight: "var(--weight-semibold)",
        fontSize: s.font,
        lineHeight: 1,
        padding: s.padding,
        borderRadius: "var(--radius-sm)",
        cursor: disabled ? "wait" : "pointer",
        opacity: disabled ? 0.5 : 1,
        transition:
          "background var(--dur-fast) var(--ease-quiet), box-shadow var(--dur-fast) var(--ease-quiet), filter var(--dur-fast) var(--ease-quiet)",
        boxShadow: "var(--shadow-sm)",
        ...v,
        ...style,
      }}
      onMouseDown={(e) => {
        if (!disabled) e.currentTarget.style.boxShadow = "var(--shadow-inset)";
      }}
      onMouseUp={(e) => {
        e.currentTarget.style.boxShadow = "var(--shadow-sm)";
      }}
      onMouseEnter={(e) => {
        if (!disabled) e.currentTarget.style.filter = "brightness(0.93)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.filter = "none";
        e.currentTarget.style.boxShadow = "var(--shadow-sm)";
      }}
      {...rest}
    >
      {iconLeft}
      {children}
      {iconRight}
    </button>
  );
}

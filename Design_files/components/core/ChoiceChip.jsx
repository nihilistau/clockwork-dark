import React from "react";

/**
 * ChoiceChip — a narrative choice pill (2–4 per turn). Keyboard
 * 1–4. Disables the instant it's clicked (the turn is in flight).
 * Shows an optional leading index key.
 */
export function ChoiceChip({
  index = null,
  disabled = false,
  onClick,
  style = {},
  children,
  ...rest
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "0.5rem",
        fontFamily: "var(--font-ui)",
        fontSize: "var(--text-base)",
        fontWeight: "var(--weight-medium)",
        color: "var(--iron-900)",
        background: "var(--accent-candle)",
        border: "var(--border-rule) solid var(--iron-700)",
        borderRadius: "var(--radius-sm)",
        padding: "0.5rem 0.85rem",
        cursor: disabled ? "wait" : "pointer",
        opacity: disabled ? 0.5 : 1,
        textAlign: "left",
        transition: "filter var(--dur-fast) var(--ease-quiet), box-shadow var(--dur-fast) var(--ease-quiet)",
        boxShadow: "var(--shadow-sm)",
        ...style,
      }}
      onMouseEnter={(e) => {
        if (!disabled) e.currentTarget.style.filter = "brightness(0.94)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.filter = "none";
      }}
      {...rest}
    >
      {index != null && (
        <span
          aria-hidden="true"
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "var(--text-xs)",
            color: "var(--rust-clock)",
            border: "1px solid var(--rust-clock)",
            borderRadius: "3px",
            padding: "0 0.3rem",
            lineHeight: 1.4,
          }}
        >
          {index}
        </span>
      )}
      <span>{children}</span>
    </button>
  );
}

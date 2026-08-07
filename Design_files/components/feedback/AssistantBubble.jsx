import React from "react";

/**
 * AssistantBubble — the ambiguous helper's voice. Rounded sans,
 * linen card with a brass left edge and an open corner toward it.
 * Form tag in tracked smallcaps. `whisper` shrinks + italicizes
 * the text and lightens it. Max 3 lines by design — never a
 * tutorial fairy.
 */
export function AssistantBubble({
  form = "cat",
  whisper = false,
  hidden = false,
  style = {},
  children,
  ...rest
}) {
  if (hidden) return null;
  return (
    <div
      role="status"
      style={{
        background: "var(--surface-card)",
        borderLeft: "var(--border-mark) solid var(--accent-brass)",
        borderRadius: "0 var(--radius-md) var(--radius-md) 0",
        padding: "0.7rem 0.85rem",
        boxShadow: "var(--shadow-card)",
        maxWidth: "100%",
        ...style,
      }}
      {...rest}
    >
      <span
        style={{
          display: "block",
          fontFamily: "var(--font-ui)",
          fontSize: "var(--text-xs)",
          textTransform: "uppercase",
          letterSpacing: "var(--tracking-label)",
          color: "var(--accent-brass)",
          marginBottom: "0.3rem",
        }}
      >
        {form}
      </span>
      <p
        style={{
          margin: 0,
          fontFamily: "var(--font-assistant)",
          fontSize: whisper ? "var(--text-sm)" : "var(--text-base)",
          fontStyle: whisper ? "italic" : "normal",
          color: whisper ? "var(--text-muted)" : "var(--text-body)",
          lineHeight: "var(--leading-snug)",
          display: "-webkit-box",
          WebkitLineClamp: 3,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
        }}
      >
        {children}
      </p>
    </div>
  );
}

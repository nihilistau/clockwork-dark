import * as React from "react";

/**
 * The ambiguous Assistant's voice: a rounded-sans linen card with a
 * brass left edge and an open corner. Max 3 lines. Slides in from the
 * hidden). Set `whisper` for the [VOICE:whisper] treatment (smaller, italic, lighter).
 */
export interface AssistantBubbleProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Canonical form tag shown in smallcaps. @default "cat" */
  form?: "cat" | "wanderer" | "child" | "tinker" | "reflection" | string;
  /** [VOICE:whisper] — smaller, italic, lighter. @default false */
  whisper?: boolean;
  /** Collapse entirely (assistant silent). @default false */
  hidden?: boolean;
  children?: React.ReactNode;
}

export function AssistantBubble(props: AssistantBubbleProps): JSX.Element | null;

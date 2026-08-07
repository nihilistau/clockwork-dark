import * as React from "react";

/**
 * A journal-column surface (the assistant column or character sheet):
 * tracked smallcaps heading, paper-calm fill, optional 2px iron ledger
 * rule on one edge. Compose StatLine / AssistantBubble inside it.
 */
export interface ScenePanelProps extends React.HTMLAttributes<HTMLElement> {
  /** Smallcaps section heading. */
  title?: React.ReactNode;
  /** Fill. @default "ledger" */
  surface?: "ledger" | "panel" | "narrative" | "card";
  /** Which edge carries the iron rule. @default "none" */
  edge?: "none" | "left" | "right";
  children?: React.ReactNode;
}

export function ScenePanel(props: ScenePanelProps): JSX.Element;

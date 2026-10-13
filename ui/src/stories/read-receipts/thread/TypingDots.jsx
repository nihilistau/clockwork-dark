/** "Being written now" (spec §9.4): shown only while the thread row says `typing`. */
import React from "react";

export default function TypingDots({ name }) {
  return (
    <li className="rr-typing" data-testid="typing-dots" aria-label={`${name} is typing`}>
      <span />
      <span />
      <span />
    </li>
  );
}

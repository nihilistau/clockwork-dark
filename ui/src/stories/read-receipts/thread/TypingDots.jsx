/** "Being written now" (spec §9.4): shown only while the thread row says `typing`. */
import React, { useEffect } from "react";

import { playSound } from "@core/sound/index.js";

/**
 * One soft tick as the dots appear (v0.24.0 spec §9.7), keyed by the thread and its last message so a re-render or a
 * re-opened thread does not tick for the same typing twice; the sound row throttles it to once in 4 s.
 */
export default function TypingDots({ name, threadId = "", lastAt = "" }) {
  useEffect(() => {
    playSound("phone.typing", { key: `typing:${threadId}@${lastAt}` });
  }, [threadId, lastAt]);
  return (
    <li className="rr-typing" data-testid="typing-dots" aria-label={`${name} is typing`}>
      <span />
      <span />
      <span />
    </li>
  );
}

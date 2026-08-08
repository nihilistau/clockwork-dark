/**
 * Cutscene letterbox.
 *
 * The server has emitted `cutscene_start` since PR10 with a video url and a
 * caption track, and nothing has ever listened for it. Milestone moments were
 * being budgeted, generated and thrown away.
 *
 * Falls back to a Ken Burns push over the still when there is no video, which
 * is the normal case: image_to_video may not exist in a given Grok build, and
 * ComfyUI AnimateDiff is expensive.
 */
import React, { useEffect, useState } from "react";
import useFocusTrap from "../hooks/useFocusTrap.js";

const SKIP_AFTER_MS = 5000;
const CAPTION_MS = 4200;

export default function Cutscene({ cutscene, onClose }) {
  const [index, setIndex] = useState(0);
  const [canSkip, setCanSkip] = useState(false);
  // Esc, the Tab wrap and focus restore all come from here. The hand-rolled
  // version handled Esc only, so Tab walked out of the letterbox into the
  // still-live play screen behind it and closing dropped focus on <body>.
  const frameRef = useFocusTrap(onClose);

  const captions = cutscene?.captions || [];

  useEffect(() => {
    if (!cutscene) return undefined;
    setIndex(0);
    setCanSkip(false);
    const skipTimer = setTimeout(() => setCanSkip(true), SKIP_AFTER_MS);
    return () => clearTimeout(skipTimer);
  }, [cutscene]);

  useEffect(() => {
    if (!cutscene || captions.length === 0) return undefined;
    if (index >= captions.length - 1) {
      // Hold the last line, then hand control back rather than trapping the
      // player in a scene with no exit.
      const done = setTimeout(onClose, CAPTION_MS);
      return () => clearTimeout(done);
    }
    const next = setTimeout(() => setIndex((i) => i + 1), CAPTION_MS);
    return () => clearTimeout(next);
  }, [cutscene, index, captions.length, onClose]);

  if (!cutscene) return null;

  const still = cutscene.image_url || cutscene.poster || "";

  return (
    <div
      className="cutscene"
      ref={frameRef}
      role="dialog"
      aria-modal="true"
      aria-label="Cutscene"
      tabIndex={-1}
    >
      <div className="cutscene__bar cutscene__bar--top" />

      <div className="cutscene__frame">
        {cutscene.video_url ? (
          <video className="cutscene__media" src={cutscene.video_url} autoPlay muted playsInline />
        ) : (
          <div
            className="cutscene__media cutscene__media--still"
            style={still ? { backgroundImage: `url(${still})` } : undefined}
          />
        )}
        <div className="cutscene__vignette" aria-hidden="true" />
      </div>

      <div className="cutscene__bar cutscene__bar--bottom">
        <p className="cutscene__caption" aria-live="polite">
          {captions[index] || ""}
        </p>
        <button
          type="button"
          className={`cutscene__skip ${canSkip ? "is-ready" : ""}`}
          onClick={onClose}
        >
          {canSkip ? "Skip" : "Esc to skip"}
        </button>
      </div>
    </div>
  );
}

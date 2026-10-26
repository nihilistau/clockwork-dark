/**
 * A voice note (spec §13.6-13.7, §18.2): a waveform, its length and its
 * transcript, always; an audio player as well once a spoken file exists
 * (TTS is off by default, so the transcript tile is the expected path).
 */
import React, { useContext, useEffect, useRef } from "react";

import { PrefsContext, voiceVolume } from "../prefs.js";
import { durationOf, mediaSrc, waveOf } from "./media.js";

export default function VoiceTile({ media, transcript = "" }) {
  // The note's volume follows master x phone (v0.24.0 spec §9.7), and a change of either reaches it at once.
  const prefs = useContext(PrefsContext);
  const audio = useRef(null);
  const volume = voiceVolume(prefs);
  useEffect(() => {
    if (audio.current) audio.current.volume = volume;
  }, [volume, media.status, media.url]);
  const words = media.transcript || transcript || "";
  const src = media.status === "ready" ? mediaSrc(media.url) : "";
  // A note with no media row (the player's own) is timed as the engine times it: 150 words a minute.
  const count = words.split(/\s+/).filter(Boolean).length;
  const seconds = Number(media.seconds) || (count ? Math.max(1, (count * 60) / 150) : 0);
  return (
    <figure className="rr-tile rr-tile--voice" data-testid={`voice-${media.mid}`}>
      <span className="rr-voice__row">
        <span className="rr-voice__wave" aria-hidden="true">
          {waveOf(media.mid).map((h, i) => (
            <span key={i} style={{ height: `${Math.round(h * 100)}%` }} />
          ))}
        </span>
        <span className="rr-voice__time">
          <span className="visually-hidden">Voice note, </span>
          {durationOf(seconds)}
        </span>
      </span>
      {src && <audio ref={audio} className="rr-voice__audio" controls preload="none" src={src} aria-label="Play the voice note" />}
      {words && <figcaption className="rr-tile__caption rr-voice__words">“{words}”</figcaption>}
    </figure>
  );
}

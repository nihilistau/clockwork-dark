import { useEffect, useRef } from "react";

import { play } from "./engine.js";
import { takeArrivalCue, turnSettled } from "./turns.js";

/** The narration <audio>'s volume: master x narration, 0 when muted (spec §7). */
export const narrationVolume = (p) => (p.muted ? 0 : (p.soundMaster ?? 0.8) * (p.volume ?? 0.8));

/**
 * turn.arrive or alert.error when a turn THIS PAGE sent ends (spec §6.3 rule 2; Plan decision 12): only with a
 * new turn payload since it went busy and the link live; a new run's settle is silent; a phone_up refusal is
 * silent. Runs every render, so its record is never stale.
 */
export function useTurnSounds({ busy, error, phoneUp, link, turns }) {
  const was = useRef({ busy, turnsAtBusy: turns });
  useEffect(() => {
    const prev = was.current;
    if (prev.busy && !busy) {
      const entry = turnSettled();
      if (entry && !entry.begin && link === "live") {
        if (error) {
          if (!phoneUp) play("alert.error");
        } else if (turns > prev.turnsAtBusy) {
          // One sound per arrival: a story's own cue (a scene door, a phone sound) already announced it.
          if (!takeArrivalCue()) play("turn.arrive");
        }
      }
    }
    was.current = { busy, turnsAtBusy: busy && !prev.busy ? turns : prev.turnsAtBusy };
  });
}

/** link.lost / link.back, only after the link has once been live. */
export function useLinkSounds(link) {
  const state = useRef({ everLive: false, last: link });
  useEffect(() => {
    const s = state.current;
    if (s.everLive && s.last === "live" && link !== "live") play("link.lost");
    if (s.everLive && s.last !== "live" && link === "live") play("link.back");
    if (link === "live") s.everLive = true;
    s.last = link;
  }, [link]);
}

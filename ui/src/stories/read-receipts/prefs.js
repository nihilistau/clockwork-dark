/**
 * The client preferences a story's PlayScreen is handed (`prefs`, v0.24.0 Plan decision 13), made reachable to the
 * components that need one without drilling it through every screen: the voice note's volume reads it.
 */
import { createContext } from "react";

export const PrefsContext = createContext(null);

/** A voice note's `<audio>` volume: master x phone, 0 when muted (spec §9.7); the defaults are core's own. */
export function voiceVolume(prefs) {
  if (!prefs) return 1;
  if (prefs.muted) return 0;
  return Math.min(1, Math.max(0, (prefs.soundMaster ?? 0.8) * (prefs.soundPhone ?? 0.9)));
}

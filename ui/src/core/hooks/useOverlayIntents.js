import { useCallback, useEffect, useState } from "react";
import { fetchOverlayIntents } from "../api.js";

// Nothing pressable and nothing held: what an overlay shows before the first answer, or when the route
// cannot be reached. A button drawn from it is drawn and not pressable.
const NONE = { scene_owns_turn: false, actions: {} };

/**
 * What an overlay may press now (v0.25.0 §8.1), fetched when it opens and again whenever `turnKey`
 * changes (a turn arrived, a refusal came back, a turn started or ended). Until the first answer nothing
 * is pressable. Returns `{offer, refresh}`; `refresh()` refetches on demand.
 */
export function useOverlayIntents(sessionId, turnKey) {
  const [offer, setOffer] = useState(NONE);
  const [nudge, setNudge] = useState(0);
  useEffect(() => {
    let live = true;
    if (!sessionId) return undefined;
    fetchOverlayIntents(sessionId)
      .then((next) => {
        if (live && next) setOffer({ scene_owns_turn: Boolean(next.scene_owns_turn), actions: next.actions || {} });
      })
      .catch(() => live && setOffer(NONE));
    return () => {
      live = false;
    };
  }, [sessionId, turnKey, nudge]);
  const refresh = useCallback(() => setNudge((n) => n + 1), []);
  return { offer, refresh };
}

/** An overlay's turn key from the play state: a new turn, a busy flip, a new error. */
export const overlayTurnKey = (state) =>
  `${state?.world?.turn_number ?? ""}|${state?.busy ? 1 : 0}|${state?.error || ""}`;

/** The offer's row for a pair, or null. */
export const offerRow = (offer, action, target) =>
  (offer?.actions?.[action] || []).find((row) => row.target === target) || null;

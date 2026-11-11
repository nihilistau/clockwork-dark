/**
 * An overlay's act (v0.25.0 §7.4): a string is the player's typed words (NEON CITY's paper and the
 * Garden's contracts overlay still send those); an `{action, target}` is an intent the server checks
 * against its overlay list under the turn lock. Anything else is dropped.
 */
export function routeOverlayAct(act, { sendText, sendIntent }) {
  if (typeof act === "string") {
    if (act.trim()) sendText(act);
    return;
  }
  if (act && typeof act.action === "string" && typeof act.target === "string") {
    sendIntent({ action: act.action, target: act.target, label: act.label || "" });
  }
}

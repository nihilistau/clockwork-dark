/** The phone's apps as the payload lists them (`phone.apps`, spec §6). */

/** The dock's four, in order (spec §18.2): the messengers and the two dating apps. */
export const DOCK = ["texts", "natter", "matchstick", "front_porch"];

/**
 * The Places app (v0.23.0 spec §14.2): the phone's own, drawn by the client from the payload's `places`
 * section (`world.places_targets`) -- apps.yaml lists no such app, so it joins the list here, only when the
 * payload carries the section (a v0.22-shaped block has none).
 */
export const PLACES_APP = { id: "places", label: "Places", kind: "places", badge: 0, capabilities: [] };

/** The home screen's apps: the payload's, and Places when the payload has the section. */
export function appsOf(phone) {
  const apps = phone.apps || [];
  return phone.places && !apps.some((a) => a.id === PLACES_APP.id) ? [...apps, PLACES_APP] : apps;
}

export function appOf(phone, id) {
  return appsOf(phone).find((a) => a.id === id) || null;
}

export function appLabel(phone, id) {
  const app = appOf(phone, id);
  return app ? app.label : id;
}

/** A thread's row by id, from the payload's `threads`. */
export function threadOf(phone, threadId) {
  return (phone.threads || []).find((t) => t.thread_id === threadId) || null;
}

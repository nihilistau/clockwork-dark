/** The phone's apps as the payload lists them (`phone.apps`, spec §6). */

/** The dock's four, in order (spec §18.2): the messengers and the two dating apps. */
export const DOCK = ["texts", "natter", "matchstick", "front_porch"];

export function appOf(phone, id) {
  return (phone.apps || []).find((a) => a.id === id) || null;
}

export function appLabel(phone, id) {
  const app = appOf(phone, id);
  return app ? app.label : id;
}

/** A thread's row by id, from the payload's `threads`. */
export function threadOf(phone, threadId) {
  return (phone.threads || []).find((t) => t.thread_id === threadId) || null;
}

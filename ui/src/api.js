/**
 * Read-only reference API.
 *
 * The journal, codex and barter screens need content the turn payload does
 * not carry: quest definitions, the location graph, economy prices and the
 * art manifest. Putting the fetches here keeps every screen a pure renderer
 * and means one place knows the URL shapes.
 *
 * Every call resolves rather than throws. A codex that explodes the play
 * screen because a lookup 404'd is worse than a codex with an empty tab.
 */

async function getJSON(path, params = {}) {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value !== "" && value != null)
  ).toString();
  const res = await fetch(query ? `${path}?${query}` : path);
  if (!res.ok) throw new Error(`server said ${res.status}`);
  return res.json();
}

export const fetchQuests = (sessionId) => getJSON("/api/quests", { session_id: sessionId });

export const fetchPlaces = (sessionId) =>
  getJSON("/api/codex/places", { session_id: sessionId });

export const fetchSouls = (sessionId) =>
  getJSON("/api/codex/souls", { session_id: sessionId });

export const fetchThings = (sessionId) =>
  getJSON("/api/codex/things", { session_id: sessionId });

export const fetchTrade = (sessionId) => getJSON("/api/trade", { session_id: sessionId });

/**
 * Resolve a manifest art key ("wolf") to a served URL.
 *
 * The client cannot read data/art/manifest.yaml, so this is the only way an
 * encounter's `art` field becomes a picture. Returns "" when the pack has
 * nothing, which callers treat as "use your own fallback".
 */
export async function fetchArtUrl(id, kind = "enemy") {
  if (!id) return "";
  try {
    const data = await getJSON("/api/art", { id, kind });
    return data.url || "";
  } catch {
    return "";
  }
}

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
 * The pack: all 74 registry items with prose, tags, weight, value and art,
 * plus what the player is carrying. data/items/*.yaml is unreadable from the
 * browser, which is why the inventory used to be a list of names.
 */
export const fetchItems = (sessionId) => getJSON("/api/items", { session_id: sessionId });

/** Every recipe, annotated with what is held and whether it can be made here. */
export const fetchRecipes = (sessionId) => getJSON("/api/recipes", { session_id: sessionId });

/** Player-settable engine config: spec, live value, override state. */
export const fetchSettings = () => getJSON("/api/settings");

/** The installed game catalogue, with playable/problems/active flags. */
export const fetchGames = () => getJSON("/api/games");

/**
 * Persist engine settings into config/local.yaml.
 *
 * Unlike the readers above this one throws: a settings write that silently
 * failed would leave the panel showing values the engine never received.
 */
export async function writeSettings(changes, { reset = false } = {}) {
  const res = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ changes, reset }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.ok) throw new Error(data.error || `server said ${res.status}`);
  return data;
}

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

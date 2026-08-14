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
 * What a new run may start as, for the active story.
 *
 * Ids come from the story's manifest and the display text from its rules file.
 * The Start screen used to hold this as a hardcoded array -- which meant a
 * second story offered its own archetypes in the picker and then drew the
 * flagship's three, and the copy had drifted from the rules file it claimed to
 * match.
 */
export const fetchArchetypes = () =>
  getJSON("/api/archetypes").then((data) => data?.archetypes || []);

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
 * Push-to-talk: audio in, transcript out.
 *
 * `transcribe_only` matters. Without it the route also runs an Assistant LLM
 * turn, which is a multi-second wait and a model call charged against a button
 * whose entire job is to put editable text in a box the player has not sent.
 *
 * Throws, like writeSettings and unlike the readers above: the mic button has a
 * visible failure state and needs to know it failed. `signal` lets the caller
 * abandon a request that has outlived the press.
 */
export async function transcribeAudio(sessionId, blob, { signal, filename } = {}) {
  const form = new FormData();
  form.append("session_id", sessionId || "");
  form.append("transcribe_only", "1");
  form.append("audio", blob, filename || "speech.webm");
  const res = await fetch("/api/voice/transcribe", { method: "POST", body: form, signal });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `server said ${res.status}`);
  const stt = data.stt || {};
  // A provider that could not answer returns 200 with success:false and says
  // why -- a missing dependency, a dead server, an unintelligible clip. That is
  // a failure to the player even though the request succeeded.
  if (!stt.success && stt.message) throw new Error(stt.message);
  return String(stt.transcript || "");
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

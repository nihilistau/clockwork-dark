/**
 * Approaches, matched to the narrator's choices (v0.21.0, spec §2.3, rule 1).
 *
 * While a scene is open the engine offers the narrator ONLY `encounter`
 * intents (engine/game/intents.py), so each legal approach it offered arrives
 * as a choice whose intent is {action: "encounter", target: <approach id>}.
 * Pressing that choice runs `encounter_approach` before narration. Typed text
 * carries no intent at all, so an approach is NEVER sent through onCustom.
 */
export function matchApproaches(encounter, choices) {
  const matched = new Map();
  if (!encounter || encounter.resolved) return matched;
  const ids = new Set((encounter.approaches || []).map((approach) => approach.id));
  for (const choice of choices || []) {
    const intent = choice && choice.intent;
    if (!intent || intent.action !== "encounter" || !ids.has(intent.target)) continue;
    if (!matched.has(intent.target)) matched.set(intent.target, choice);
  }
  return matched;
}

/** The ids of the matched choices: what a play screen with an approach panel hides. */
export function matchedChoiceIds(encounter, choices) {
  return new Set([...matchApproaches(encounter, choices).values()].map((choice) => choice.id));
}

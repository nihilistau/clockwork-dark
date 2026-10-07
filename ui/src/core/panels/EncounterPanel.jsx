/**
 * The encounter's terms and approaches, for a story on core's panels
 * (v0.21.0, spec §4.5). Generic and smaller than the flagship's: the threat
 * and its resolve, the round (0-based on the wire), the intro on the first
 * round, and one button per approach -- its text, "no roll" or the skill and
 * difficulty words, a cost when there is one.
 *
 * RULE 1. A matched approach presses ITS CHOICE (`onChoose`); an unmatched
 * one is drawn, `aria-disabled`, "not offered this turn". Nothing here calls
 * `onCustom`. When every narrator choice was matched the choice row is hidden
 * and these take the digits (`bindDigits`); then the panel is never
 * collapsed, because it holds the only moves (plan decision 11), and each
 * pressable approach wears its key's number, the choice row's badge, counted
 * over the pressable ones only (an unmatched approach has no key).
 */
import React, { useMemo } from "react";

import { useDigitKeys } from "../hooks/useDigitKeys.js";
import Panel from "./Panel.jsx";
import { matchApproaches } from "./approaches.js";

function terms(encounter, threat) {
  const parts = [];
  if (threat.resolve_max) parts.push(`resolve ${threat.resolve} of ${threat.resolve_max}`);
  if (encounter.max_rounds) parts.push(`round ${Number(encounter.round || 0) + 1} of ${encounter.max_rounds}`);
  return parts.join(" · ");
}

function meta(approach) {
  const how = approach.auto ? "no roll" : [approach.skill, approach.difficulty].filter(Boolean).join(" · ");
  const cost = Number(approach.cost_gold) || 0;
  return [how, cost > 0 ? `costs ${cost}` : ""].filter(Boolean).join(" · ");
}

const NONE = {};

export default function EncounterPanel({ state, onChoose, controlsOff = false, bindDigits = false, blocked = false, narrow = false }) {
  const encounter = state?.world?.encounter || NONE;
  const live = Object.keys(encounter).length > 0 && !encounter.resolved;
  const matched = useMemo(() => matchApproaches(encounter, state?.choices), [encounter, state?.choices]);
  const pressable = useMemo(
    () => (live ? (encounter.approaches || []).filter((approach) => matched.has(approach.id)).map((approach) => matched.get(approach.id)) : []),
    [live, encounter, matched]
  );
  const off = controlsOff || Boolean(state?.busy);
  useDigitKeys(pressable, onChoose, live && bindDigits && !off && !blocked);

  if (!live) return null;
  const approaches = encounter.approaches || [];
  const threat = encounter.threat || {};
  const fold = narrow && !bindDigits;
  return (
    <Panel id="encounter" title={threat.name || "Encounter"} className="encpanel" collapsible={fold} defaultOpen={!fold}>
      <p className="encpanel__terms">{terms(encounter, threat)}</p>
      {Number(encounter.round || 0) === 0 && encounter.intro && <p className="encpanel__intro">{encounter.intro}</p>}
      <div className="encpanel__approaches" role="group" aria-label="Approaches">
        {approaches.map((approach) => {
          const choice = matched.get(approach.id);
          const disabled = off || !choice;
          const index = choice ? pressable.indexOf(choice) : -1;
          const key = bindDigits && index >= 0 && index < 9 ? String(index + 1) : "";
          return (
            <button
              key={approach.id}
              type="button"
              className="encpanel__approach"
              aria-disabled={disabled ? "true" : undefined}
              aria-keyshortcuts={key || undefined}
              onClick={() => {
                if (!disabled) onChoose(choice);
              }}
            >
              {key && (
                <span className="chip__key encpanel__key" aria-hidden="true">
                  {key}
                </span>
              )}
              <span className="encpanel__text">{approach.text}</span>
              <span className="encpanel__meta">{meta(approach)}</span>
              {!choice && <span className="encpanel__note">not offered this turn</span>}
            </button>
          );
        })}
      </div>
    </Panel>
  );
}

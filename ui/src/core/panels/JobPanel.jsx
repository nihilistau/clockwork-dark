/**
 * The job panel (v0.21.0, spec §4.2): the house, the stages as a stepper, the
 * alarm and prep in words with marks lit to their place. `world.job` from
 * `GameState._job_block`; shown only while `active` is non-null. `at` is
 * 0-based. The alarm's last word ("raised") is drawn in the danger token.
 *
 * THE VEILED RULE. The alarm and prep arrive as words, ordered by `scales`;
 * a word's place only lights marks. No place is printed, and no number,
 * percentage or width is made from one. Core's words only ("The job",
 * "Alarm", "Prep"): the house, the stages and the bands are the payload's.
 */
import React from "react";

import { SHORT_QUERY, useMedia } from "../hooks/useMedia.js";
import Marks from "./Marks.jsx";
import Panel from "./Panel.jsx";
import { scaleIndex } from "./scale.js";

export default function JobPanel({ state, narrow = false }) {
  // Collapsed by default on a phone AND on a short window (final review
  // finding 19, K2): its heading already carries the current stage, and
  // expanded it held the narration log to its floor at 1366x768.
  const short = useMedia(SHORT_QUERY);
  const job = state?.world?.job;
  const active = job?.active;
  if (!active) return null;
  const scales = job.scales || {};
  const alarmScale = scales.alarm || [];
  const prepScale = scales.prep || [];
  const alarmAt = scaleIndex(alarmScale, active.alarm);
  const prepAt = scaleIndex(prepScale, job.prep);
  const raised = alarmAt >= 0 && alarmAt === alarmScale.length - 1;
  const stages = active.stages || [];
  return (
    <Panel id="job" title={`The job — ${active.premise_name}`} collapsible defaultOpen={!narrow && !short} summary={active.stage_label}>
      <ol className="job__stages">
        {stages.map((label, i) => (
          <li
            key={i}
            className={`job__stage ${i < active.at ? "is-done" : ""} ${i === active.at ? "is-current" : ""}`.trim()}
            aria-current={i === active.at ? "step" : undefined}
          >
            {i === active.at ? active.stage_label || label : label}
          </li>
        ))}
      </ol>
      <p className={`job__alarm ${raised ? "is-danger" : ""}`.trim()}>
        Alarm: <span className="job__word">{active.alarm}</span>{" "}
        <Marks count={Math.max(0, alarmScale.length - 1)} lit={Math.max(0, alarmAt)} danger={raised} />
      </p>
      <p className="job__prep">
        Prep: <span className="job__word">{job.prep}</span>{" "}
        <Marks count={Math.max(0, prepScale.length - 1)} lit={Math.max(0, prepAt)} />
      </p>
    </Panel>
  );
}

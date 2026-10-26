/**
 * READ RECEIPTS' world layer (v0.23.0 spec §14.1): the room the player is in, outside the phone. Built from
 * core's parts -- the scene plate, the narrative log and the choice row -- and the buzz banner. Its choices
 * are core's `state.choices`, sent through `onChoose` like any story's.
 *
 * While the phone is up the row is greyed with a note, because the server refuses a world choice then
 * (409 `phone_up`); the layer shows only WORDS of the phone's (the buzz's count and names), never a message.
 *
 * "Also here" (v0.23.0 addendum 4 W9): who else is in the room, from `world.here` -- the people the player knows
 * who are here by chance, then the background people on shift -- by name only, never a number. It sits on the
 * plate, as the place's label does, so it takes no height from the log, the choices or the compose box.
 */
import React, { useEffect, useRef, useState } from "react";

import { playSound } from "@core/sound/index.js";

import MicButton from "../../../core/parts/MicButton.jsx";
import ChoiceRow from "../../../core/parts/ChoiceRow.jsx";
import NarrativeLog from "../../../core/parts/NarrativeLog.jsx";
import ScenePlate from "../../../core/parts/ScenePlate.jsx";
import { controlsLive } from "../../../core/store.js";
import Buzz from "./Buzz.jsx";
import Companion, { Household } from "./Companion.jsx";

export const PUT_DOWN_NOTE = "Put the phone down to act";

/** The "Also here" line: names only (contacts first, then the people around), or nothing. */
export function AlsoHere({ here }) {
  const names = (Array.isArray(here) ? here : [])
    .filter((row) => row && typeof row.name === "string" && row.name)
    .sort((a, b) => (a.kind === "contact" ? 0 : 1) - (b.kind === "contact" ? 0 : 1))
    .map((row) => row.name);
  if (!names.length) return null;
  return (
    <p className="rr-also-here" data-testid="rr-also-here">
      Also here: {names.join(", ")}
    </p>
  );
}

export default function World({ state, phone = null, onChoose, onCustom = null, phoneUp = false, onPickUp = () => {}, blocked = false }) {
  const block = phone || (state.world && state.world.phone) || null;
  const world = (block && block.world) || {};
  const scene = block && block.scene && block.scene.pid ? block.scene : null;
  const off = !controlsLive(state);
  // The compose box (spec A4 W6): core's form, greyed while the phone is up or the controls are off.
  const [text, setText] = useState("");
  const box = useRef(null);
  const greyed = off || phoneUp;
  // `/` focuses it while the world is forward (core's key stands down for a story-owned screen).
  useEffect(() => {
    if (!onCustom || phoneUp || blocked) return undefined;
    function onKey(event) {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      const tag = event.target && event.target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || (event.target && event.target.isContentEditable)) return;
      event.preventDefault();
      if (box.current) box.current.focus();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCustom, phoneUp, blocked]);
  function submit(event) {
    event.preventDefault();
    const value = text.trim();
    if (!value || greyed || !onCustom) return;
    setText("");
    onCustom(value);
    playSound("choice.send");
  }
  // The plate already names the place it has a name for; the label is for a plate that has none.
  const where = state.world && (state.world.location_name || state.world.location_id) ? "" : world.location || "";
  return (
    <section className="rr-world" aria-label="Where you are" tabIndex={-1}>
      <div className="rr-world__plate">
        <ScenePlate state={state} />
        {where && <p className="rr-world__where">{where}</p>}
        {scene && <Companion person={scene} />}
        {!scene && <Household household={world.household} />}
        <AlsoHere here={world.here} />
      </div>
      {!phoneUp && <Buzz buzz={world.buzz} onPickUp={onPickUp} />}
      {!phoneUp && (
        <button type="button" className="rr-world__pickup" data-sound="none" onClick={onPickUp}>
          Pick up the phone
        </button>
      )}
      <div className="rr-world__log">
        <NarrativeLog entries={state.log || []} busy={state.busy} />
      </div>
      <div className="rr-world__choices">
        <ChoiceRow
          choices={state.choices || []}
          busy={off}
          blocked={blocked}
          onChoose={onChoose}
          focusSignal={state.choiceFocus || 0}
          settled={!state.busy && (state.log || []).length > 0}
          disabledNote={phoneUp ? PUT_DOWN_NOTE : ""}
        />
      </div>
      {onCustom && (
        <form className="compose rr-world__compose" data-testid="rr-compose" onSubmit={submit}>
          <input
            className="compose__input"
            ref={box}
            value={text}
            onChange={(e) => {
              if (!greyed) setText(e.target.value);
            }}
            placeholder={phoneUp ? PUT_DOWN_NOTE : "Or say what you do…  (press / to jump here)"}
            readOnly={greyed}
            aria-disabled={greyed ? "true" : undefined}
            aria-label="Custom action"
          />
          <MicButton
            sessionId={state.sessionId}
            disabled={greyed || !state.sessionId}
            onTranscript={(said) => setText((t) => (t ? `${t} ${said}` : said))}
          />
          <button type="submit" className="btn" data-sound="none" disabled={greyed || !text.trim()}>
            Send
          </button>
        </form>
      )}
    </section>
  );
}

/**
 * Sophia's channel — the left column, and the Companion tab on a phone.
 *
 * WHY THE GARDEN NEEDED ONE AT ALL. The plugin declared no `Aside`, and
 * `Play.jsx` hides the Companion tab entirely when a story declares none
 * (`TABS.filter(t => t.id !== "assistant" || Aside)`). So the story whose whole
 * subject is a live companion was the one story with no companion tab, and on a
 * narrow viewport she had nowhere to be at all.
 *
 * WHAT FEEDS IT. `state.presence`, which is the payload's `assistant` block --
 * and for a story running a CHARACTER rather than an assistant the server puts
 * her there too, marked with `character`. That is the seam working as designed:
 * the column is "the other voice", and core does not have to learn which
 * stories have which. `assistant` is the transient line for the turn just
 * taken; `presence` survives a silent turn, which is why the face does not
 * vanish when she chooses to say nothing.
 *
 * SHE IS ALLOWED TO SAY NOTHING. `spoke: false` is a real turn and not a
 * missing one, so silence renders as silence rather than as an empty bubble --
 * a Sovereign who declines to comment is making a point.
 *
 * THE ANALYST SWITCH LIVES HERE because this is the story's own surface and
 * because `analyst` was previously inert: the plugin declared
 * `initialState: {analyst: false}`, `Wrap` read `state.story.analyst ??
 * loadAnalyst()`, and nothing in the client ever wrote it -- so the preference
 * could only be changed by editing localStorage by hand. It is a player
 * preference in the player's own language, not a debug flag.
 */
import React from "react";

import PaintFrame from "@core/parts/PaintFrame.jsx";
import { useAnalyst, useSetAnalyst } from "../analyst.js";

/**
 * Her face, or the wash that stands in for it.
 *
 * The portrait is resolved server-side from the story's art manifest. Six of
 * the Garden's plates are missing, so the fallback has to be lit rather than
 * empty -- a hole reads as a broken build, a wash reads as a painting that has
 * not arrived.
 */
/**
 * NO `form` CAPTION, and that is a correction rather than an omission.
 *
 * `presence.form` is the ASSISTANT MIND's current face -- one of The Clockwork
 * Dark's five, defaulting to `cat` -- and `assistant_presence` ships it for
 * every story because the field is on the shared payload. Rendering it here
 * put the word "cat" under Sophia's portrait on the Garden's first frame,
 * which is the flagship's state leaking through a slot this story shares with
 * it. She is a character with one face and a mood; the five-faced companion is
 * somebody else's mechanic.
 */
function Face({ portrait }) {
  return (
    <PaintFrame
      size="portrait"
      wash="radial-gradient(120% 100% at 50% 30%, var(--wg-rose), var(--wg-soil-deep))"
      className="companion__face"
    >
      {portrait && (
        <img
          className="paint__img"
          src={portrait}
          // Decorative: her name and her mood are already on screen as text,
          // and a screen-reader user hearing a filename-derived description of
          // a painting is worse served than by the caption they already have.
          alt=""
          loading="lazy"
          draggable="false"
        />
      )}
    </PaintFrame>
  );
}

export default function Companion({ state }) {
  const analyst = useAnalyst();
  const setAnalyst = useSetAnalyst();
  const presence = state.presence || {};
  const line = state.assistant?.text || presence.text || "";
  const spoke = Boolean(state.assistant?.spoke ?? presence.spoke);

  return (
    <aside className="companion" aria-label="Sophia">
      <Face portrait={presence.portrait} />

      {/* Named, not titled "Companion". This column is never anybody else in
          this story, and the server marks her with `character` for exactly
          that reason. */}
      <h2 className="companion__who">Sophia</h2>

      {spoke && line ? (
        <p className="companion__line">{line}</p>
      ) : (
        <p className="companion__silent">
          {state.busy
            ? "She is deciding how much to say."
            : "She says nothing, and lets that be the answer."}
        </p>
      )}

      <label className="companion__switch">
        <input
          type="checkbox"
          checked={Boolean(analyst)}
          onChange={(event) => setAnalyst(event.target.checked)}
        />
        Show me the numbers
        <span className="companion__switch-note">
          Prints the integer beside each meter that has one. A veiled value has
          no number to print and stays a word.
        </span>
      </label>
    </aside>
  );
}

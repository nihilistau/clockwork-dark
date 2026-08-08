/**
 * The Wicked Garden component kit, on one page.
 *
 * WHY A PAGE AND NOT A SCREENSHOT
 * -------------------------------
 * These components have no story to live in yet -- `games/wicked-garden/` does
 * not exist, so no server can send them a turn. The alternative to a kit page is
 * committing components nobody has ever rendered, which is how a design system
 * ends up full of things that do not compile.
 *
 * EVERYTHING ON THIS PAGE IS A FIXTURE AND SAYS SO
 * ------------------------------------------------
 * The numbers, names and prose below are invented for the purpose of exercising
 * a control. They are not a save, not a session and not a preview of a real
 * run, and the banner at the top says exactly that in the player's own view --
 * not only in a comment where nobody looking at the page can read it. Fixtures
 * that look like live data are the single easiest way to convince a reviewer
 * that a feature works.
 *
 * The analyst switch is real: it drives the same context the story plugin
 * provides, so flipping it here exercises the same code path a player would.
 */
import React, { useState } from "react";

import { AnalystContext } from "../analyst.js";
import ContractScroll from "../parts/ContractScroll.jsx";
import CourtBoard from "../parts/CourtBoard.jsx";
import EndingGallery from "../parts/EndingGallery.jsx";
import EpilogueCard from "../parts/EpilogueCard.jsx";
import OmenSting from "../parts/OmenSting.jsx";
import { PetalButton, WaxSealButton } from "../parts/Buttons.jsx";
import { HourglassMeter, VineMeter } from "../parts/Meters.jsx";

const TERMS = [
  {
    id: "protection",
    tag: "Protection",
    text: "No lesser thing of the Garden may touch you while the thread holds.",
    cost: "hers to withdraw",
  },
  {
    id: "scent",
    tag: "Name",
    text: "You carry her scent. Every court that meets you will know whose you are.",
    cost: "social",
  },
  {
    id: "leave",
    tag: "Freedom",
    text: "Removable only with her leave, or by rare law, or by cold iron.",
    cost: "three keys, none yours",
  },
];

const COURT = {
  centre: { id: "sophia", name: "Sophia", standing: "interested · possessive" },
  satellites: [
    { id: "ashen", name: "Ashen Vale", standing: "unknown scent" },
    { id: "thornwake", name: "Thornwake", standing: "the law of the seat" },
    { id: "lior", name: "Lior", standing: "mirrors wait" },
  ],
  roots: [{ id: "briar", name: "Mother Briar", standing: "a heartbeat under the roots" }],
  edges: [
    { from: "sophia", to: "ashen", kind: "grievance", strain: 1.6 },
    { from: "sophia", to: "thornwake", kind: "obligation", strain: 0.8 },
    { from: "sophia", to: "lior", kind: "watching", strain: 0.4 },
    { from: "sophia", to: "briar", kind: "obligation", strain: 1.9 },
    { from: "ashen", to: "lior", kind: "watching", strain: 0.6 },
    { from: "thornwake", to: "briar", kind: "grievance", strain: 1.1 },
  ],
};

const ENDINGS = [
  {
    id: "E1",
    title: "The Door Home",
    tier: "locked",
    tease: "A hedge you have walked past forty times, and a gap in it that was not there.",
    lockReason: "You have not been told the terms on which anyone leaves.",
    gate: "autonomy >= 55 and knowledge >= 40 and not thrall_locked",
  },
  {
    id: "E2",
    title: "Equal & Eternal",
    tier: "locked",
    tease: "Two thrones is a stupid arrangement. She has been thinking about it anyway.",
    lockReason: "She does not yet believe you could stand beside her.",
    gate: "favor >= 70 and autonomy >= 55 and equality_seed >= 2 and not thrall_mark",
  },
  {
    id: "E3",
    title: "Beloved Thrall",
    tier: "silhouette",
    tease: "Something kept very well indeed.",
    lockReason: "You have refused every collar you were offered.",
    gate: "favor >= 75 and autonomy <= 40 and desire >= 60 and thrall_path_open",
  },
  {
    id: "E4",
    title: "Consumed",
    tier: "unlocked",
    tease: "The Garden does not waste anything. That is the kindest thing about it.",
  },
  {
    id: "E5",
    title: "Usurper",
    tier: "silhouette",
    tease: "A crown is only a hat that nobody has taken off you yet.",
    lockReason: "You have found neither the key nor the deal that opens the crypt.",
    gate: "knowledge >= 70 and (briar_key or briar_deal) and autonomy >= 60",
  },
  {
    id: "E6",
    title: "Other Hungers",
    tier: "silhouette",
    tease: "Not every door out of a garden goes home.",
    lockReason: "No other court has offered you anything.",
    gate: "ashen_route >= 2 and (passport or service_thread)",
  },
];

function Section({ title, note, children }) {
  return (
    <section className="kit__section">
      <h2 className="kit__head">{title}</h2>
      {note && <p className="kit__note">{note}</p>}
      <div className="kit__stage">{children}</div>
    </section>
  );
}

export default function Kit() {
  const [analyst, setAnalyst] = useState(false);
  const [whispers, setWhispers] = useState(true);
  const [omen, setOmen] = useState(null);
  const [answer, setAnswer] = useState("");
  const [favor, setFavor] = useState(62);

  return (
    <AnalystContext.Provider value={analyst}>
      <div className="kit">
        <header className="kit__masthead">
          <h1 className="kit__title">
            The Wicked <span>Garden</span> — component kit
          </h1>
          {/* Said on the page, not only in a comment. */}
          <p className="kit__disclaimer">
            <b>Every value on this page is a fixture.</b> There is no
            <code> games/wicked-garden/ </code> on the server yet, so nothing
            here is connected to a session, a save, or a turn. These are the
            controls, driven by hand, so they can be looked at before the story
            that needs them exists.
          </p>

          <div className="kit__switches">
            <label className="kit__switch">
              <input
                type="checkbox"
                checked={analyst}
                onChange={(e) => setAnalyst(e.target.checked)}
              />
              Show me the numbers
              <span className="kit__switch-note">
                the player-facing name for <code>analyst_mode</code>, default off
              </span>
            </label>
            <label className="kit__switch">
              <input
                type="checkbox"
                checked={whispers}
                onChange={(e) => setWhispers(e.target.checked)}
              />
              Implication whispers
              <span className="kit__switch-note">default ON, per 06-UI-UX</span>
            </label>
          </div>
        </header>

        <Section
          title="PetalButton"
          note="Choices bloom outward; a declined choice wilts. The second line is the implication whisper — a consequence stated, never an ending id."
        >
          <div className="kit__row">
            <PetalButton
              whisper="She will like this."
              showWhisper={whispers}
              onClick={() => setAnswer("Took the wine.")}
            >
              Take the wine she poured
            </PetalButton>
            <PetalButton
              whisper="This spends the Briar Key."
              showWhisper={whispers}
              onClick={() => setAnswer("Spent the key.")}
            >
              Open the crypt door
            </PetalButton>
            <PetalButton tone="danger" whisper="The court will hear of it." showWhisper={whispers}>
              Say her name in front of Thornwake
            </PetalButton>
            <PetalButton disabled whisper="You have nothing left to trade." showWhisper={whispers}>
              Offer the mirror shard
            </PetalButton>
          </div>
        </Section>

        <Section
          title="WaxSealButton"
          note="Three peers. Renegotiate shares the seal with Accept and differs only in tint; Refuse is cold silver, the danger palette, at identical hit geometry."
        >
          <div className="kit__row">
            <WaxSealButton action="accept" onClick={() => setAnswer("Accepted.")} />
            <WaxSealButton action="renegotiate" onClick={() => setAnswer("Renegotiated.")} />
            <WaxSealButton action="refuse" onClick={() => setAnswer("Refused.")} />
            <WaxSealButton action="accept" disabled />
          </div>
          {answer && <p className="kit__echo">last action: {answer}</p>}
        </Section>

        <Section
          title="ContractScroll"
          note="Mark a clause to renegotiate that clause; renegotiate with nothing marked to reopen the whole hand. Silver ink is Ashen Vale's; gold is the Garden's own."
        >
          <ContractScroll
            title="The Guest-Right of the Heart Grove"
            offeredBy="Sophia"
            preamble="Read it. I would rather you understood it than agreed to it."
            terms={TERMS}
            seal="a word, said aloud, in your own voice"
            onAccept={(t) => setAnswer(`accepted${t ? ` (marked: ${t})` : ""}`)}
            onRenegotiate={(t) => setAnswer(`renegotiating ${t || "the whole hand"}`)}
            onRefuse={() => setAnswer("refused cleanly")}
          />
          <ContractScroll
            title="Passage, Of A Sort"
            offeredBy="Ashen Vale"
            ink="silver"
            preamble="Information only. No passport. You will want the passport later; that is rather the point."
            terms={[
              { id: "info", tag: "Knowledge", text: "One true answer, asked plainly.", cost: "one favour, unnamed" },
              { id: "silence", tag: "Silence", text: "You did not hear it from him.", cost: "binding" },
            ]}
            seal="a coin, halved"
            onRenegotiate={(t) => setAnswer(`renegotiating ${t || "the whole hand"}`)}
          />
        </Section>

        <Section
          title="VineMeter · HourglassMeter"
          note="Non-numeric by default: the stage word is the value, and it is what a screen reader is told. The switch at the top adds the integer beside it — it never replaces it. A veiled meter has no integer to add, so it stays a word however the switch is set."
        >
          <div className="kit__meters">
            <VineMeter name="favor" value={favor} />
            <VineMeter name="autonomy" value={38} />
            <VineMeter name="corruption" value={12} />
            <VineMeter name="knowledge" value={71} />
            <VineMeter name="desire" band="strong" />
            <HourglassMeter days={40} gardenDays={4} label="Time debt" />
            <HourglassMeter days={110} gardenDays={11} label="Time debt (spent)" />
          </div>
          <label className="kit__slider">
            Drive favor by hand
            <input
              type="range"
              min="0"
              max="100"
              value={favor}
              onChange={(e) => setFavor(Number(e.target.value))}
            />
          </label>
          <p className="kit__note">
            The fifth row is <b>veiled</b>: the server sent the band{" "}
            <code>strong</code> and no number at all. Its vine is quantised into
            five hard steps so a width cannot be measured back into an integer.
          </p>
        </Section>

        <Section
          title="CourtBoard"
          note="A political map. The edges carry the meaning and the nodes are only where they land — gold is an obligation, dashed silver a watching, dotted a grievance. Thickness is strain, not warmth. Mother Briar hangs under Sophia as a root, not as a peer."
        >
          <CourtBoard {...COURT} onSelect={(id) => setAnswer(`inspected ${id}`)} />
        </Section>

        <Section
          title="EndingGallery"
          note="Three tiers. A silhouette is out of reach from here and is drawn as an outline with no interior, because a shape you cannot reach must not look like a picture of a thing you can. Turn the switch on to see the gates."
        >
          <EndingGallery
            endings={ENDINGS}
            onSwear={(id) => setAnswer(`swore toward ${id}`)}
            onLook={(id) => setAnswer(`looked at ${id}`)}
          />
        </Section>

        <Section
          title="OmenSting"
          note="Fires once per id. Pressing the same button twice does nothing, which is the whole contract — an omen that repeats is a status bar with a flash on it. Any key or click dismisses it."
        >
          <div className="kit__row">
            <button
              type="button"
              className="btn btn--sm"
              onClick={() =>
                setOmen({
                  id: "hourglass-first-grain",
                  // The product dwell is 2.6s. The kit effectively holds it
                  // until dismissed: this is a control being INSPECTED, not a
                  // beat being played, and 2.6s is not long enough to read a
                  // sting you are studying. `dwell` is a real prop, so this is
                  // a demo setting rather than a different component.
                  dwell: 600000,
                  kicker: "An omen",
                  line: "An hourglass of ash appears at the edge of sight. The first grain falls.",
                })
              }
            >
              Fire the hourglass omen
            </button>
            <button
              type="button"
              className="btn btn--sm"
              onClick={() =>
                setOmen({
                  id: "point-of-no-return",
                  dwell: 600000,
                  kicker: "The last day",
                  tone: "rose",
                  line: "Choose. The Garden will grow something from this either way.",
                })
              }
            >
              Fire the point-of-no-return sting
            </button>
          </div>
          <p className="kit__note">
            Under <code>prefers-reduced-motion</code> the flash is a still card.
            A photosensitive player can suppress it entirely and still be told —
            the omen carries information, so the words survive the visual.
          </p>
          <OmenSting omen={omen} onDone={() => setOmen(null)} />
        </Section>

        <Section
          title="EpilogueCard"
          note="Two cards, always: what happened in the waking world and what happened in the Garden. The time line computes the mortal cost from the Garden days at the story's own exchange rate, so the two can never disagree."
        >
          <EpilogueCard
            id="E1d"
            title="The Door Home — Hollow"
            gardenDays={12}
            hollow
            mortal="The hedge lets you through on a Tuesday. Your key still fits. The lock has been changed twice since it was cut, and both times someone kept the old one, just in case."
            garden="The chair you used is still at the table. Nobody has moved it and nobody sits in it, and this is the most sentimental thing the Garden has ever done."
            echo="Go on, then. I will not watch you to the gate; I have some dignity."
          />
        </Section>

        <footer className="kit__foot">
          <p>
            Specified by <code>docs/design/09-UI-COMPONENT-KIT.md</code>,{" "}
            <code>06-UI-UX.md</code> and <code>concept/meta/nine-slice.json</code>.
            Geometry is taken from the vector sheet rather than the raster kit:
            the JPEGs are still on <code>#00FF00</code> chroma and have not been
            keyed to alpha, so dropping them in would render a green box.
          </p>
        </footer>
      </div>
    </AnalystContext.Provider>
  );
}

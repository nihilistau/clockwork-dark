/* GameScene — interactive recreation of The Clockwork Dark scene.
   "Lit by tallow and mistrust": a cold, grim Ash & Thorn frame —
   slate shadow and bleak air — with a slight tinker-brass accent and
   the journal glowing as the one warm, lit thing. Composes the DS
   components with a faked turn loop and a phase switcher.
   Globals (bundle): Button, ChoiceChip, Badge, StatLine,
   AssistantBubble, DiceToast, ScenePanel, WorldClock. */

const NS = window.TheClockworkDarkDesignSystem_4a0a88;
const { Button, ChoiceChip, Badge, StatLine, AssistantBubble, DiceToast, ScenePanel, WorldClock } = NS;
const { useState, useRef, useEffect } = React;

// ---- Fake content (drawn from data/lore + economy) ----
const SCENES = {
  forest_clearing: {
    title: "The Forest Clearing",
    caption: "Birch margin · dawn mist",
    tint: "radial-gradient(120% 78% at 52% 6%, rgba(214,178,108,.22), transparent 48%), linear-gradient(178deg,#10171a 0%,#18211d 42%,#26302a 74%,#34392e 100%)",
    narration:
      "You wake where the birch gives way to fern. Mushroom circles, game trails that double back when watched. Smoke from Edgewood drifts west — even though the wind blows south.",
    choices: [
      { id: "smoke", text: "Walk toward the smoke" },
      { id: "forage", text: "Forage the clearing" },
      { id: "listen", text: "Listen" },
    ],
    assistant: { form: "cat", text: "The smoke is bread, not burning. Probably." },
  },
  edgewood_square: {
    title: "Edgewood Square",
    caption: "Communal oven · failing light",
    tint: "radial-gradient(100% 76% at 64% 12%, rgba(214,150,80,.26), transparent 46%), linear-gradient(178deg,#10161a 0%,#1b2020 44%,#33291d 80%,#43321f 100%)",
    narration:
      "Timber frames lean together around the communal oven. A shrine to unnamed saints keeps its candle. Maris hums at the bakery door, flour on her sleeves — villagers say she hums to keep the gears quiet.",
    choices: [
      { id: "bakery", text: "Visit Maris at the bakery" },
      { id: "board", text: "Read the notice board" },
      { id: "shrine", text: "Study the unfinished mural" },
    ],
    assistant: { form: "cat", text: "Stay near the oven light. It is honest." },
  },
  tinker_caravan: {
    title: "The Tinker Caravan",
    caption: "Nine-pin tent · last of the dusk",
    tint: "radial-gradient(110% 78% at 50% 20%, rgba(190,118,58,.28), transparent 50%), linear-gradient(178deg,#12120f 0%,#241a13 46%,#3c2818 80%,#553a22 100%)",
    narration:
      "Nine brass pins glint in Ilya's scarf. Charms hang from the tent ribs; chalk symbols mark roads that shift when the wheat turns wrong. A sympathy lamp burns with no flame you can name.",
    choices: [
      { id: "barter", text: "Barter for a sympathy charm" },
      { id: "map", text: "Ask about the road to Millhaven" },
      { id: "leave", text: "Step back into the dusk" },
    ],
    assistant: { form: "tinker", text: "Ilya counts you twice. Once for now. Once for later." },
  },
};

const ORDER = ["forest_clearing", "edgewood_square", "tinker_caravan"];
const PHASES = ["dormant", "stirring", "spreading", "consuming"];

function SceneVisual({ scene, phase }) {
  const wrong = phase === "spreading" || phase === "consuming";
  return (
    <div style={{
      position: "relative", height: "min(38vh, 300px)", minHeight: 190,
      background: scene.tint, overflow: "hidden",
      borderBottom: "1px solid rgba(214,178,108,.22)",
    }}>
      {/* candle bloom — the one warm note */}
      <div className="cw-flicker" style={{
        position: "absolute", inset: 0,
        background: "radial-gradient(54% 46% at 52% 14%, rgba(214,178,108,.24), transparent 62%)",
        mixBlendMode: "screen",
      }} />
      {wrong && <div style={{
        position: "absolute", inset: 0, background: "var(--corruption)",
        opacity: phase === "consuming" ? 0.28 : 0.15, mixBlendMode: "color",
      }} />}
      {/* oil grain */}
      <div style={{ position: "absolute", inset: 0, backgroundImage: "var(--texture-paper)", opacity: 0.62, mixBlendMode: "multiply" }} />
      {/* cold cinematic vignette */}
      <div style={{ position: "absolute", inset: 0, boxShadow: "inset 0 0 140px 30px rgba(6,9,9,.86)" }} />
      {/* letterbox lips */}
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 30, background: "linear-gradient(180deg, rgba(6,9,9,.9), transparent)" }} />
      <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 56, background: "linear-gradient(0deg, rgba(6,9,9,.75), transparent)" }} />
      <span style={{
        position: "absolute", top: 9, right: 13, fontFamily: "var(--font-mono)", fontSize: 10,
        letterSpacing: ".12em", textTransform: "uppercase", color: "rgba(214,178,108,.42)",
      }}>ComfyUI still · {scene.title}</span>
      <div style={{ position: "absolute", left: 15, bottom: 13, display: "flex", gap: 8, alignItems: "center" }}>
        <Badge tone="candle" style={{ background: "rgba(14,16,12,.6)", color: "var(--tallow-300)", borderColor: "var(--tallow-700)" }}>{scene.caption}</Badge>
        {wrong && <Badge tone="corruption" style={{ background: "rgba(16,20,8,.6)" }}>Wrong rain</Badge>}
      </div>
    </div>
  );
}

function GameScene() {
  const [started, setStarted] = useState(false);
  const [archetype, setArchetype] = useState("wayfarer");
  const [sceneIdx, setSceneIdx] = useState(0);
  const [phase, setPhase] = useState("stirring");
  const [log, setLog] = useState([]);
  const [busy, setBusy] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [toast, setToast] = useState(null);
  const [stats, setStats] = useState({ hp: "18/18", stamina: 6, gold: "0.00", day: 11, time: "Dusk" });
  const [input, setInput] = useState("");
  const logRef = useRef(null);

  const sceneId = ORDER[sceneIdx];
  const scene = SCENES[sceneId];

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  function begin() {
    setStarted(true);
    setLog([{ kind: "narration", text: scene.narration }]);
    setTimeout(() => setAssistantOpen(true), 600);
  }

  function rollDice() {
    const roll = 1 + Math.floor(Math.random() * 20);
    const mod = 2, dc = 13;
    const outcome = roll === 20 ? "Boon" : roll === 1 ? "Complication" : roll + mod >= dc ? "Success" : "Failure";
    setToast({ roll, modifier: mod, dc, outcome });
    setTimeout(() => setToast(null), 1500);
    return outcome;
  }

  function choose(choice) {
    if (busy) return;
    setBusy(true);
    setLog((l) => [...l, { kind: "player", text: choice.text }]);
    const outcome = rollDice();
    setTimeout(() => {
      let next = sceneIdx;
      if (choice.id === "smoke" || choice.id === "bakery") next = Math.min(sceneIdx + 1, ORDER.length - 1);
      if (choice.id === "map") next = 2;
      const nextScene = SCENES[ORDER[next]];
      const tail = outcome === "Failure" ? " You slip — the moment costs you a breath of stamina."
        : outcome === "Boon" ? " Something others missed catches your eye. A free clue." : "";
      setLog((l) => [...l, { kind: "narration", text: nextScene.narration + tail }]);
      setStats((s) => ({
        ...s,
        stamina: Math.max(0, s.stamina - (outcome === "Failure" ? 1 : 0)),
        time: s.time === "Dusk" ? "Night" : s.time === "Night" ? "Deep night" : "Dusk",
        day: next !== sceneIdx ? s.day + 1 : s.day,
      }));
      if (next !== sceneIdx) {
        setSceneIdx(next); setAssistantOpen(false);
        setTimeout(() => setAssistantOpen(true), 700);
      }
      setBusy(false);
    }, 700);
  }

  function sendCustom(e) {
    e.preventDefault();
    const t = input.trim();
    if (!t || busy) return;
    setInput("");
    choose({ id: "custom", text: t });
  }

  // ---- Start screen ----
  if (!started) {
    const archetypes = [
      { id: "wayfarer", name: "Wayfarer", note: "Cloak, staff, road boots" },
      { id: "hearthkeeper", name: "Hearthkeeper", note: "Apron, flour, warm colors" },
      { id: "tinker", name: "Tinker-apprentice", note: "Tool belt, brass pins, chalk" },
    ];
    return (
      <div data-phase={phase} style={frameStyle}>
        <Atmosphere />
        <div style={{ position: "relative", flex: 1, display: "grid", placeItems: "center", padding: 24 }}>
          <div style={{
            width: 470, background: "linear-gradient(168deg, #1d2119 0%, #14160f 100%)",
            padding: "34px 36px", borderRadius: 3,
            boxShadow: "0 0 0 1px rgba(214,178,108,.22), 0 34px 90px -22px rgba(0,0,0,.92), 0 0 130px -8px rgba(214,178,108,.12)",
            borderTop: "1px solid rgba(214,178,108,.14)", borderLeft: "var(--border-mark) solid var(--rust-clock)",
          }}>
            <img src="../../assets/wordmark.svg" alt="The Clockwork Dark" style={{ width: 300, marginBottom: 18, filter: "drop-shadow(0 2px 12px rgba(0,0,0,.6))" }} />
            <p style={{
              fontFamily: "var(--font-narration)", fontSize: "var(--text-lg)",
              lineHeight: "var(--leading-relaxed)", color: "var(--text-narration)", margin: "0 0 22px",
            }}>
              You wake at the margin of an old forest, the last comfortable village a smudge of smoke to the west. The roads have begun to change when no one is watching. Choose how you came to be here.
            </p>
            <p style={smallcaps}>Traveler</p>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 22 }}>
              {archetypes.map((a) => (
                <button key={a.id} onClick={() => setArchetype(a.id)} style={{
                  textAlign: "left", display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "11px 14px", cursor: "pointer", fontFamily: "var(--font-ui)",
                  background: archetype === a.id ? "rgba(214,178,108,.14)" : "rgba(255,255,255,.03)",
                  border: archetype === a.id ? "var(--border-rule) solid var(--rust-clock)" : "var(--border-rule) solid rgba(214,178,108,.16)",
                  borderRadius: "var(--radius-sm)",
                  boxShadow: archetype === a.id ? "var(--glow-candle)" : "none",
                  transition: "all var(--dur-fast) var(--ease-quiet)",
                }}>
                  <span style={{ fontWeight: 600, color: "var(--text-on-dark)" }}>{a.name}</span>
                  <span style={{ fontSize: "var(--text-sm)", color: "var(--text-muted)" }}>{a.note}</span>
                </button>
              ))}
            </div>
            <Button variant="primary" size="lg" onClick={begin} style={{ width: "100%", justifyContent: "center" }}>
              Step into the clearing
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // ---- Scene ----
  return (
    <div data-phase={phase} style={frameStyle}>
      <Atmosphere />
      {/* header */}
      <header style={{
        position: "relative", display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "11px 20px", background: "linear-gradient(180deg,#090d0e,#0f1210)",
        borderBottom: "1px solid rgba(214,178,108,.2)", boxShadow: "0 2px 16px rgba(0,0,0,.7)", zIndex: 2,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
          <img src="../../assets/gear-motif.svg" alt="" className="cw-turn" style={{ width: 22, opacity: 0.92, filter: "brightness(1.3) drop-shadow(0 0 8px rgba(190,118,58,.5))" }} />
          <h1 style={{
            margin: 0, color: "var(--text-on-dark)", fontFamily: "var(--font-ui)",
            fontSize: "var(--text-base)", fontWeight: 600, textTransform: "uppercase",
            letterSpacing: "var(--tracking-title)",
          }}>{scene.title}</h1>
        </div>
        <WorldClock day={stats.day} time={stats.time} discovered={phase !== "dormant"} />
      </header>

      {/* grid */}
      <main style={{
        position: "relative", flex: 1, display: "grid",
        gridTemplateColumns: "var(--col-assistant) 1fr var(--col-sheet)", minHeight: 0, zIndex: 1,
      }}>
        {/* assistant column — cold ash */}
        <ScenePanel surface="panel" edge="right" style={{
          display: "flex", flexDirection: "column",
          background: "linear-gradient(180deg, #1a2220 0%, #10150f 100%)",
          borderRight: "1px solid rgba(214,178,108,.13)", boxShadow: "inset -18px 0 32px -26px #000",
        }}>
          <p style={{ ...smallcaps, color: "var(--tallow-300)" }}>Assistant</p>
          <AssistantBubble form={scene.assistant.form} hidden={!assistantOpen}
            style={{ boxShadow: "var(--shadow-raise), 0 0 30px -6px rgba(214,178,108,.42)" }}>
            {scene.assistant.text}
          </AssistantBubble>
          <div style={{ flex: 1 }} />
          <p style={{ fontFamily: "var(--font-narration)", fontStyle: "italic", fontSize: "var(--text-sm)",
            color: "rgba(214,210,190,.34)", margin: 0, lineHeight: 1.45 }}>
            Something watches from the stillness without moving.
          </p>
        </ScenePanel>

        {/* narrative column — the lit journal */}
        <section style={{
          display: "flex", flexDirection: "column", minHeight: 0,
          background: "#0a0d0a", boxShadow: "0 0 100px -12px rgba(214,178,108,.14)",
        }}>
          <SceneVisual scene={scene} phase={phase} />
          <div ref={logRef} className="cw-log" style={{
            position: "relative", flex: 1, overflowY: "auto", overflowX: "hidden", padding: "22px 26px", minHeight: 0,
            background: "linear-gradient(180deg, #1c2019 0%, #14160f 100%)",
            backgroundImage: "var(--texture-paper)",
            boxShadow: "inset 0 18px 26px -20px rgba(0,0,0,.7), inset 0 -18px 26px -20px rgba(0,0,0,.6)",
          }}>
            {log.map((entry, i) => entry.kind === "narration" ? (
              <p key={i} style={{
                fontFamily: "var(--font-narration)", fontSize: "var(--text-lg)",
                lineHeight: "var(--leading-relaxed)", color: "var(--text-narration)",
                margin: "0 0 16px", textWrap: "pretty",
              }}>{entry.text}</p>
            ) : (
              <p key={i} style={{
                fontFamily: "var(--font-ui)", fontSize: "var(--text-sm)", fontStyle: "italic",
                color: "var(--accent-candle)", margin: "0 0 16px", paddingLeft: 12,
                borderLeft: "var(--border-mark) solid var(--rust-500)",
              }}>You chose: {entry.text}</p>
            ))}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, padding: "14px 26px 12px",
            background: "#0d100d", borderTop: "1px solid rgba(214,178,108,.13)" }}>
            {scene.choices.map((c, i) => (
              <ChoiceChip key={c.id} index={i + 1} disabled={busy} onClick={() => choose(c)}
                style={{ boxShadow: "0 3px 12px -3px rgba(0,0,0,.6)" }}>
                {c.text}
              </ChoiceChip>
            ))}
          </div>
          <form onSubmit={sendCustom} style={{
            display: "flex", gap: 8, padding: "0 26px 16px 26px", background: "#0d100d",
          }}>
            <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Or type an action…"
              style={{
                flex: 1, padding: "10px 12px", border: "var(--border-hair) solid #2f342c",
                borderRadius: "var(--radius-sm)", fontFamily: "var(--font-ui)", fontSize: "var(--text-base)",
                background: "#161a14", color: "var(--text-on-dark)",
              }} />
            <Button variant="primary" type="submit" disabled={busy}>Send</Button>
          </form>
        </section>

        {/* sheet column */}
        <ScenePanel title={null} surface="ledger" edge="left" style={{
          background: "linear-gradient(180deg, #181811 0%, #12120b 100%)",
          borderLeft: "1px solid rgba(214,178,108,.13)", boxShadow: "inset 18px 0 32px -26px #000",
        }}>
          <p style={{ ...smallcaps, color: "var(--tallow-300)" }}>Traveler</p>
          <div>
            <DarkStat label="HP" value={stats.hp} />
            <DarkStat label="Stamina" value={stats.stamina} />
            <DarkStat label="Gold" value={stats.gold} accent />
            <DarkStat label="Location" value={sceneId.replace("_", " ")} />
          </div>
          <p style={{ ...smallcaps, color: "var(--tallow-300)", marginTop: 18 }}>Inventory</p>
          <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 7 }}>
            {["Loaf of bread ×1", "Whetstone ×1", "Wild mushroom ×3", "Tallow candle ×2"].map((it) => (
              <li key={it} style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)", color: "var(--linen-300)" }}>{it}</li>
            ))}
          </ul>
        </ScenePanel>
      </main>

      {/* footer */}
      <footer style={{
        position: "relative", display: "flex", alignItems: "center", gap: 16, padding: "9px 20px",
        background: "linear-gradient(0deg,#090d0e,#0f1210)", color: "var(--text-on-dark)",
        fontSize: "var(--text-sm)", borderTop: "1px solid rgba(214,178,108,.2)", zIndex: 2,
      }}>
        <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-candlelight)" }}>
          Day {stats.day} · {stats.time} · {phase === "spreading" || phase === "consuming" ? "Wrong rain" : "Overcast"}
        </span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "var(--tracking-label)" }}>Evil phase</span>
        <div style={{ display: "flex", gap: 4 }}>
          {PHASES.map((p) => (
            <button key={p} onClick={() => setPhase(p)} title={p} style={{
              fontFamily: "var(--font-ui)", fontSize: "var(--text-xs)", textTransform: "capitalize",
              padding: "4px 10px", cursor: "pointer", borderRadius: "var(--radius-sm)",
              border: "1px solid " + (phase === p ? "var(--accent-candle)" : "#2f342c"),
              background: phase === p ? "rgba(214,178,108,.18)" : "transparent",
              color: phase === p ? "var(--text-candlelight)" : "var(--text-muted)",
              boxShadow: phase === p ? "0 0 14px -4px rgba(214,178,108,.6)" : "none",
              transition: "all var(--dur-fast) var(--ease-quiet)",
            }}>{p}</button>
          ))}
        </div>
      </footer>

      {/* dice toast */}
      {toast && (
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", pointerEvents: "none", zIndex: 5 }}>
          <div className="cw-toast" style={{ filter: "drop-shadow(0 14px 34px rgba(0,0,0,.7))" }}>
            <DiceToast {...toast} />
          </div>
        </div>
      )}
    </div>
  );
}

function DarkStat({ label, value, accent }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline",
      padding: "5px 0", borderBottom: "1px solid rgba(214,178,108,.13)" }}>
      <span style={{ fontFamily: "var(--font-ui)", fontSize: "var(--text-xs)", textTransform: "uppercase",
        letterSpacing: "var(--tracking-label)", color: "rgba(214,206,184,.58)" }}>{label}</span>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)", fontVariantNumeric: "tabular-nums",
        color: accent ? "var(--tallow-300)" : "var(--linen-200)" }}>{value}</span>
    </div>
  );
}

// Ambient overlay: cold corner shadow + faint air over the whole frame.
function Atmosphere() {
  return (
    <div aria-hidden="true" style={{ position: "absolute", inset: 0, pointerEvents: "none", zIndex: 0,
      boxShadow: "inset 0 0 220px 50px rgba(4,6,6,.74)",
      background: "radial-gradient(140% 120% at 50% -10%, transparent 58%, rgba(4,6,6,.55))" }} />
  );
}

const frameStyle = {
  position: "relative", width: "100%", height: "100%", minHeight: 0,
  display: "flex", flexDirection: "column", overflow: "hidden",
  background: "radial-gradient(120% 100% at 50% 0%, #12181a, #060909 72%)",
};
const smallcaps = {
  margin: "0 0 10px", fontFamily: "var(--font-ui)", fontSize: "var(--text-xs)",
  fontWeight: 600, textTransform: "uppercase", letterSpacing: "var(--tracking-label)",
  color: "var(--text-body)",
};

window.GameScene = GameScene;

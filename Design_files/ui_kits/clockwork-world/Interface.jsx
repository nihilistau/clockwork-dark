/* Interface — the HUD anatomy and panel designs. */

const IF = window.TheClockworkDarkDesignSystem_4a0a88;

function Card({ title, children, span }) {
  return (
    <div style={{ gridColumn: span ? `span ${span}` : "auto", borderRadius: "var(--radius-md)",
      background: "linear-gradient(180deg,#0e1311,#090c0a)", border: "1px solid rgba(214,178,108,.14)",
      boxShadow: "0 14px 34px -18px rgba(0,0,0,.8)", overflow: "hidden" }}>
      <div style={{ padding: "12px 16px", borderBottom: "1px solid rgba(214,178,108,.1)" }}>
        <span style={{ fontFamily: "var(--font-ui)", fontSize: "var(--text-xs)", fontWeight: 700,
          textTransform: "uppercase", letterSpacing: "var(--tracking-label)", color: "var(--accent-brass)" }}>{title}</span>
      </div>
      <div style={{ padding: 18 }}>{children}</div>
    </div>
  );
}

function HudAnatomy() {
  const cell = (bg, label, sub, extra) => (
    <div style={{ background: bg, border: "1px solid rgba(214,178,108,.16)", borderRadius: 3,
      padding: "10px 11px", display: "flex", flexDirection: "column", gap: 4, ...extra }}>
      <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, fontWeight: 700, textTransform: "uppercase",
        letterSpacing: ".08em", color: "var(--text-candlelight)" }}>{label}</span>
      <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-muted)" }}>{sub}</span>
    </div>
  );
  return (
    <div style={{ display: "grid", gridTemplateRows: "auto 1fr auto", gap: 6, height: 300 }}>
      {cell("linear-gradient(180deg,#0c0f0d,#0a0c0a)", "Header", "Scene name · World clock")}
      <div style={{ display: "grid", gridTemplateColumns: "0.8fr 1.6fr 0.9fr", gap: 6, minHeight: 0 }}>
        {cell("linear-gradient(180deg,#141a16,#0d120f)", "Assistant", "200px · slides from left")}
        <div style={{ display: "grid", gridTemplateRows: "1.1fr auto auto", gap: 6, minHeight: 0 }}>
          {cell("linear-gradient(160deg,#1a201b,#10140f)", "Scene visual", "ComfyUI still · 38vh")}
          {cell("linear-gradient(180deg,#1c2019,#14160f)", "Narrative log", "SSE serif · the lit journal")}
          {cell("#0d100d", "Choices + input", "2–4 chips · free text")}
        </div>
        {cell("linear-gradient(180deg,#181811,#11120b)", "Character sheet", "220px · HP · STA · inv")}
      </div>
      {cell("linear-gradient(0deg,#0c0f0d,#0a0c0a)", "Footer", "Day · time · weather · phase")}
    </div>
  );
}

function Letterbox() {
  return (
    <div style={{ position: "relative", aspectRatio: "2.39/1", background: "#000", borderRadius: 3, overflow: "hidden" }}>
      <div style={{ position: "absolute", inset: 0, background:
        "radial-gradient(80% 80% at 50% 30%, rgba(190,118,58,.22), transparent 60%), linear-gradient(180deg,#10140f,#1a160f)" }} />
      <div style={{ position: "absolute", inset: 0, backgroundImage: "var(--texture-paper)", opacity: .5, mixBlendMode: "multiply" }} />
      <div style={{ position: "absolute", inset: 0, boxShadow: "inset 0 0 90px 20px rgba(6,8,5,.85)" }} />
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, padding: "12px 16px",
        background: "linear-gradient(0deg, rgba(6,8,5,.9), transparent)" }}>
        <p style={{ margin: 0, fontFamily: "var(--font-narration)", fontStyle: "italic", fontSize: "var(--text-base)",
          color: "rgba(226,220,201,.92)", textShadow: "0 1px 3px #000" }}>
          "The village clock stopped at a hour that never was."</p>
      </div>
      <button style={{ position: "absolute", top: 10, right: 12, fontFamily: "var(--font-ui)", fontSize: 11,
        padding: "3px 9px", borderRadius: 3, cursor: "pointer", color: "rgba(226,220,201,.7)",
        background: "rgba(12,12,9,.5)", border: "1px solid rgba(214,178,108,.25)" }}>Skip</button>
    </div>
  );
}

function CombatSheet() {
  const { Button } = IF;
  return (
    <div style={{ position: "relative", borderRadius: 3, overflow: "hidden",
      background: "linear-gradient(180deg,#15100f,#0c0a0a)", padding: 16, border: "1px solid rgba(122,45,42,.4)" }}>
      <div style={{ position: "absolute", inset: 0, boxShadow: "inset 0 0 60px 8px rgba(107,45,45,.45)", pointerEvents: "none" }} />
      <div style={{ position: "relative" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <span style={{ fontFamily: "var(--font-narration)", fontSize: "var(--text-lg)", color: "var(--text-on-dark)" }}>Brass-toothed lamb</span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)", color: "var(--status-danger)" }}>HP 9</span>
        </div>
        <div style={{ height: 6, borderRadius: 3, marginTop: 8, background: "rgba(0,0,0,.5)", overflow: "hidden" }}>
          <div style={{ width: "64%", height: "100%", background: "linear-gradient(90deg, var(--blood-quiet), #a14)" }} />
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
          <Button variant="danger" size="sm">Strike</Button>
          <Button variant="secondary" size="sm">Ward</Button>
          <Button variant="secondary" size="sm">Flee</Button>
        </div>
        <p style={{ margin: "12px 0 0", fontFamily: "var(--font-ui)", fontSize: 11, fontStyle: "italic", color: "var(--text-muted)" }}>
          No battle animations in v0.1 — still image with a red vignette pulse.</p>
      </div>
    </div>
  );
}

function Interface() {
  const { AssistantBubble, DiceToast, ChoiceChip, WorldClock, Badge, StatLine } = IF;
  const phases = window.CW_DATA.phases;
  return (
    <div>
      <SectionHead kicker="The Interface" title="HUD & panel design"
        lede="A traveler's journal crossed with a clockmaker's ledger. No MMO clutter, no floating UI, no Awareness meter — hidden mechanics stay hidden until discovered in-world." />
      <div style={{ padding: "26px 40px 40px", display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 22 }}>

        <Card title="HUD anatomy — global layout" span={2}>
          <HudAnatomy />
        </Card>

        <Card title="Assistant bubble — forms & whisper">
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <AssistantBubble form="cat" style={{ boxShadow: "var(--shadow-raise), 0 0 26px -6px rgba(214,178,108,.4)" }}>The smoke is bread, not burning. Probably.</AssistantBubble>
            <AssistantBubble form="wanderer" whisper style={{ boxShadow: "var(--shadow-raise)" }}>Roads change when the wheat turns wrong.</AssistantBubble>
          </div>
        </Card>

        <Card title="Dice toast — verbatim engine result">
          <div style={{ display: "flex", flexDirection: "column", gap: 12, alignItems: "flex-start" }}>
            <DiceToast roll={14} modifier={2} dc={13} outcome="Success" />
            <DiceToast roll={4} modifier={1} dc={12} outcome="Failure" />
            <DiceToast roll={20} modifier={0} outcome="Boon" />
          </div>
        </Card>

        <Card title="Choice chips — 2–4, keyboard 1–4">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            <ChoiceChip index={1}>Walk toward smoke</ChoiceChip>
            <ChoiceChip index={2}>Forage the clearing</ChoiceChip>
            <ChoiceChip index={3}>Listen</ChoiceChip>
            <ChoiceChip index={4} disabled>Wait…</ChoiceChip>
          </div>
        </Card>

        <Card title="World clock & weather — diegetic">
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ background: "var(--surface-chrome)", padding: "10px 14px", borderRadius: 3, display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontFamily: "var(--font-ui)", fontSize: 12, textTransform: "uppercase", letterSpacing: ".1em", color: "var(--text-on-dark)" }}>Edgewood Square</span>
              <WorldClock day={12} time="Evening" discovered />
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <Badge tone="neutral">Overcast</Badge>
              <Badge tone="candle">Market day</Badge>
              <Badge tone="corruption">Wrong rain</Badge>
            </div>
          </div>
        </Card>

        <Card title="Character sheet — the ledger">
          <StatLine label="HP" value="14/18" />
          <StatLine label="Stamina" value="6" />
          <StatLine label="Gold" value="0.42" accent />
          <StatLine label="Location" value="edgewood" />
        </Card>

        <Card title="Cutscene — 2.39:1 letterbox">
          <Letterbox />
        </Card>

        <Card title="Combat sheet — rare, minimal">
          <CombatSheet />
        </Card>

        <Card title="Phase transition — UI behavior" span={2}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
            {phases.map((p, i) => (
              <div key={p.key} data-phase={p.key} style={{ borderRadius: 3, overflow: "hidden", border: "1px solid rgba(214,178,108,.16)" }}>
                <div style={{ height: 52, background: "var(--surface-scene)", display: "grid", placeItems: "center",
                  boxShadow: "inset 0 0 26px rgba(6,8,5,.7)" }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--accent-candle)" }}>Day {[4, 11, 22, 38][i]}</span>
                </div>
                <div style={{ padding: "10px 12px", background: "linear-gradient(180deg,#0e1311,#0a0d0b)" }}>
                  <div style={{ fontFamily: "var(--font-ui)", fontSize: 12, fontWeight: 700, textTransform: "uppercase",
                    letterSpacing: ".06em", color: "var(--text-candlelight)" }}>{p.label}</div>
                  <div style={{ fontFamily: "var(--font-narration)", fontSize: 12, fontStyle: "italic", color: "rgba(226,220,201,.62)", marginTop: 4 }}>{p.mood}</div>
                  <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>{p.ui}</div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

window.InterfaceKit = Interface;

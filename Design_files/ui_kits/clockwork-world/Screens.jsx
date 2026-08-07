/* Screens — three full interface mockups: Trade, Bakery, Millhaven.
   Composes DS components in grim-dark Ash & Thorn. */

const SC = window.TheClockworkDarkDesignSystem_4a0a88;
const { useState: useScState, useEffect: useScEffect, useRef: useScRef } = React;

function ScreenFrame({ tint, caption, children, corrupted }) {
  return (
    <div style={{ borderRadius: "var(--radius-md)", overflow: "hidden",
      border: "1px solid rgba(214,178,108,.16)", boxShadow: "0 20px 50px -22px rgba(0,0,0,.85)",
      background: "linear-gradient(180deg,#0c100e,#080a09)" }}>
      <div style={{ position: "relative", height: 150 }}>
        <PaintFrame tint={tint} caption={caption} corrupted={corrupted} height={150} />
      </div>
      <div style={{ padding: 20 }}>{children}</div>
    </div>
  );
}

/* ---------------- TRADE / BARTER OVERLAY ---------------- */
function TradeScreen() {
  const { Button, Badge } = SC;
  const give = [
    { name: "Wild mushroom", qty: 3, tint: "#8a6b4a", worth: 1 },
    { name: "Resin", qty: 2, tint: "#a9683a", worth: 1 },
    { name: "River clay", qty: 1, tint: "#7a6a52", worth: 1 },
  ];
  const get = [
    { name: "Sympathy charm", qty: 1, tint: "#b8863f", worth: 25, brass: true },
    { name: "Tinker knowledge map", qty: 1, tint: "#caa05a", worth: 20 },
  ];
  const [offered, setOffered] = useScState([true, true, false]);
  const giveTotal = give.reduce((s, g, i) => s + (offered[i] ? g.worth * g.qty : 0), 0);
  const getTotal = 45;
  const balance = giveTotal - getTotal;

  const Row = ({ it, on, toggle }) => (
    <button onClick={toggle} style={{ display: "flex", alignItems: "center", gap: 12, width: "100%",
      textAlign: "left", cursor: toggle ? "pointer" : "default", padding: "9px 11px", borderRadius: "var(--radius-sm)",
      background: on === false ? "rgba(255,255,255,.02)" : "rgba(214,178,108,.07)",
      border: "1px solid " + (on === false ? "rgba(214,178,108,.1)" : "rgba(214,178,108,.22)"),
      marginBottom: 8 }}>
      <span style={{ width: 30, height: 30, flex: "none", borderRadius: it.brass ? "50%" : 6,
        background: `linear-gradient(160deg, ${it.tint}, rgba(0,0,0,.55))`,
        border: it.brass ? "1px solid rgba(214,178,108,.5)" : "1px solid rgba(0,0,0,.4)",
        boxShadow: "inset 0 1px 2px rgba(255,255,255,.2)" }} />
      <span style={{ flex: 1, fontFamily: "var(--font-ui)", fontSize: "var(--text-base)", color: "var(--text-on-dark)" }}>
        {it.name} <span style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 12 }}>×{it.qty}</span>
      </span>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-candlelight)" }}>{it.worth * it.qty}c</span>
    </button>
  );

  return (
    <ScreenFrame tint="radial-gradient(110% 78% at 50% 18%, rgba(190,118,58,.30), transparent 52%), linear-gradient(178deg,#12120f 0%,#241a13 50%,#553a22 100%)" caption="Ilya's wagon · barter, not coin">
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 16 }}>
        <h3 style={{ margin: 0, fontFamily: "var(--font-narration)", fontSize: "var(--text-xl)", color: "var(--text-on-dark)" }}>Barter with Ilya of the Nine Pins</h3>
        <Badge tone="brass">Caravan</Badge>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        <div>
          <p style={kickerS}>You give</p>
          {give.map((g, i) => <Row key={g.name} it={g} on={offered[i]}
            toggle={() => setOffered((o) => o.map((v, j) => j === i ? !v : v))} />)}
          <p style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-muted)", fontStyle: "italic", margin: "4px 2px" }}>Tap to add or hold back.</p>
        </div>
        <div>
          <p style={kickerS}>Ilya offers</p>
          {get.map((g) => <Row key={g.name} it={g} on={true} toggle={null} />)}
        </div>
      </div>
      {/* balance beam */}
      <div style={{ marginTop: 18, padding: "14px 16px", borderRadius: "var(--radius-sm)",
        background: "rgba(0,0,0,.3)", border: "1px solid rgba(214,178,108,.16)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontFamily: "var(--font-ui)", fontSize: 12, textTransform: "uppercase", letterSpacing: ".08em", color: "var(--text-muted)" }}>Balance</span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-md)",
            color: balance >= 0 ? "#8fae5a" : "var(--status-danger)" }}>
            {balance >= 0 ? "Fair — Ilya nods" : `${Math.abs(balance)}c short`}
          </span>
        </div>
        <div style={{ height: 8, marginTop: 10, borderRadius: 4, background: "rgba(0,0,0,.5)", overflow: "hidden", position: "relative" }}>
          <div style={{ position: "absolute", left: "50%", top: 0, bottom: 0, width: 1, background: "rgba(214,178,108,.4)" }} />
          <div style={{ position: "absolute", left: balance >= 0 ? "50%" : (50 + balance / getTotal * 50) + "%",
            right: balance >= 0 ? (50 - Math.min(balance, getTotal) / getTotal * 50) + "%" : "50%", top: 0, bottom: 0,
            background: balance >= 0 ? "linear-gradient(90deg,#5a6f3a,#8fae5a)" : "linear-gradient(90deg,#6b2d2d,#a14)" }} />
        </div>
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 16, justifyContent: "flex-end" }}>
        <Button variant="ghost">Step back</Button>
        <Button variant="primary" disabled={balance < 0}>Strike the bargain</Button>
      </div>
    </ScreenFrame>
  );
}

/* ---------------- BAKERY DOMESTIC UI ---------------- */
function OvenTimer() {
  const TOTAL = 12 * 60;
  const [left, setLeft] = useScState(7 * 60 + 42);
  const [running, setRunning] = useScState(true);
  useScEffect(() => {
    if (!running) return;
    const id = setInterval(() => setLeft((l) => (l <= 0 ? TOTAL : l - 1)), 1000);
    return () => clearInterval(id);
  }, [running]);
  const pct = (1 - left / TOTAL) * 100;
  const mm = String(Math.floor(left / 60)).padStart(2, "0");
  const ss = String(left % 60).padStart(2, "0");
  const done = left <= 0;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
      <div style={{ position: "relative", width: 168, height: 168, borderRadius: "50%",
        background: `conic-gradient(var(--accent-candle) ${pct}%, rgba(255,255,255,.06) ${pct}%)`,
        display: "grid", placeItems: "center", boxShadow: "0 0 40px -8px rgba(214,178,108,.45)" }}>
        <div style={{ position: "absolute", inset: 12, borderRadius: "50%",
          background: "radial-gradient(circle at 50% 36%, #2a1c10, #120c07)",
          boxShadow: "inset 0 0 30px rgba(214,140,60,.4)", display: "grid", placeItems: "center" }}>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 30, fontVariantNumeric: "tabular-nums",
              color: done ? "#8fae5a" : "var(--text-candlelight)" }}>{done ? "Ready" : `${mm}:${ss}`}</div>
            <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, textTransform: "uppercase", letterSpacing: ".14em", color: "var(--text-muted)", marginTop: 3 }}>Oven · loaf</div>
          </div>
        </div>
      </div>
      <button onClick={() => setRunning((r) => !r)} style={{ fontFamily: "var(--font-ui)", fontSize: 12,
        padding: "5px 14px", borderRadius: "var(--radius-sm)", cursor: "pointer", color: "var(--text-candlelight)",
        background: "rgba(214,178,108,.1)", border: "1px solid rgba(214,178,108,.3)" }}>
        {running ? "Tend the fire" : "Stoke"}
      </button>
    </div>
  );
}

function BakeryScreen() {
  const { Button, Badge } = SC;
  const recipes = [
    { name: "Loaf of bread", needs: ["Flour", "Water", "Salt"], time: "12m", active: true },
    { name: "Mushroom pottage", needs: ["Wild mushroom ×2", "Water", "Herbs"], time: "20m" },
    { name: "Festival cake", needs: ["Flour", "Honey", "Dried fruit"], time: "35m" },
  ];
  return (
    <ScreenFrame tint="radial-gradient(90% 90% at 32% 56%, rgba(214,150,80,.46), transparent 60%), linear-gradient(178deg,#1a120c,#3a2414 60%,#6b4524 100%)" caption="The Hearth Bakery · morning prep">
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 16 }}>
        <h3 style={{ margin: 0, fontFamily: "var(--font-narration)", fontSize: "var(--text-xl)", color: "var(--text-on-dark)" }}>Maris's hearth — baking</h3>
        <Badge tone="candle">Domestic</Badge>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: 24, alignItems: "start" }}>
        <OvenTimer />
        <div>
          <p style={kickerS}>Recipes</p>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {recipes.map((r) => (
              <div key={r.name} style={{ padding: "11px 13px", borderRadius: "var(--radius-sm)",
                background: r.active ? "rgba(214,178,108,.08)" : "rgba(255,255,255,.02)",
                border: "1px solid " + (r.active ? "rgba(214,178,108,.28)" : "rgba(214,178,108,.1)") }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                  <span style={{ fontFamily: "var(--font-narration)", fontSize: "var(--text-lg)", color: "var(--text-on-dark)" }}>{r.name}</span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-candlelight)" }}>{r.time}</span>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                  {r.needs.map((n) => (
                    <span key={n} style={{ fontFamily: "var(--font-ui)", fontSize: 11, padding: "2px 8px", borderRadius: 999,
                      background: "rgba(0,0,0,.3)", border: "1px solid rgba(214,178,108,.16)", color: "rgba(226,220,201,.72)" }}>{n}</span>
                  ))}
                </div>
                {r.active && <div style={{ marginTop: 11 }}><Button variant="primary" size="sm">Knead &amp; set</Button></div>}
              </div>
            ))}
          </div>
          <p style={{ fontFamily: "var(--font-narration)", fontStyle: "italic", fontSize: "var(--text-base)",
            color: "rgba(214,178,108,.6)", margin: "16px 0 0" }}>She hums to keep the gears quiet.</p>
        </div>
      </div>
    </ScreenFrame>
  );
}

/* ---------------- MILLHAVEN MILITIA SCENE ---------------- */
function MillhavenScreen() {
  const { Button, ChoiceChip, Badge, StatLine, AssistantBubble } = SC;
  return (
    <ScreenFrame tint="radial-gradient(120% 90% at 50% 16%, rgba(150,166,170,.20), transparent 55%), linear-gradient(178deg,#0c1114,#1d262b 55%,#39434a 100%)" caption="Millhaven gate · cold rain">
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 14 }}>
        <h3 style={{ margin: 0, fontFamily: "var(--font-narration)", fontSize: "var(--text-xl)", color: "var(--text-on-dark)" }}>The palisade gate</h3>
        <Badge tone="danger">Duty</Badge>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 220px", gap: 22 }}>
        <div>
          <p style={{ fontFamily: "var(--font-narration)", fontSize: "var(--text-lg)", lineHeight: "var(--leading-relaxed)",
            color: "var(--text-narration)", margin: 0 }}>
            Sergeant Sera meets you under the dripping banner, scar pale in the lantern light. Refugees thin the mud road behind her. "The road from the Heartlands is wrong tonight," she says. "I can spare you the gate, or your silence. Not both."
          </p>
          <div style={{ marginTop: 16 }}>
            <AssistantBubble form="wanderer" whisper style={{ boxShadow: "var(--shadow-raise)" }}>
              She is not lying. That is what frightens her.
            </AssistantBubble>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 18 }}>
            <ChoiceChip index={1}>Show your road map</ChoiceChip>
            <ChoiceChip index={2}>Offer to stand the watch</ChoiceChip>
            <ChoiceChip index={3}>Ask what she saw</ChoiceChip>
          </div>
        </div>
        <div style={{ padding: "14px 15px", borderRadius: "var(--radius-sm)",
          background: "linear-gradient(180deg,#11161a,#0b0f12)", border: "1px solid rgba(150,166,170,.2)" }}>
          <p style={{ ...kickerS, color: "#9aa6a8" }}>Gate watch</p>
          <StatLine label="Militia" value="6 fit" />
          <StatLine label="Refugees" value="23" />
          <StatLine label="Rations" value="4 days" accent />
          <StatLine label="Road" value="wrong" />
          <p style={{ ...kickerS, color: "#9aa6a8", marginTop: 16 }}>Orders</p>
          <p style={{ fontFamily: "var(--font-ui)", fontSize: 12, color: "rgba(226,220,201,.7)", lineHeight: 1.5, margin: 0 }}>
            Hold the gate. Admit the hungry. Report any brass.
          </p>
          <div style={{ marginTop: 14 }}><Button variant="danger" size="sm" style={{ width: "100%", justifyContent: "center" }}>Sound the bell</Button></div>
        </div>
      </div>
    </ScreenFrame>
  );
}

const kickerS = { margin: "0 0 12px", fontFamily: "var(--font-ui)", fontSize: "var(--text-xs)",
  fontWeight: 700, textTransform: "uppercase", letterSpacing: "var(--tracking-label)", color: "var(--accent-brass)" };

function Screens() {
  const [tab, setTab] = useScState("trade");
  const subs = [
    { id: "trade", label: "Trade · Barter" },
    { id: "bakery", label: "Bakery · Hearth" },
    { id: "millhaven", label: "Millhaven · Gate" },
  ];
  const View = { trade: TradeScreen, bakery: BakeryScreen, millhaven: MillhavenScreen }[tab];
  return (
    <div>
      <SectionHead kicker="The Screens" title="Scenes & domestic UI"
        lede="Beyond the forest turn: a barter overlay (goods, never floating coin), Maris's baking hearth (domestic UI as polished as adventure UI), and the cold militia gate at Millhaven." />
      <div style={{ padding: "20px 40px 40px" }}>
        <div style={{ display: "flex", gap: 8, marginBottom: 22 }}>
          {subs.map((s) => (
            <button key={s.id} onClick={() => setTab(s.id)} style={{
              fontFamily: "var(--font-ui)", fontSize: "var(--text-sm)", fontWeight: 600,
              padding: "8px 16px", cursor: "pointer", borderRadius: "var(--radius-sm)",
              border: "1px solid " + (tab === s.id ? "var(--accent-candle)" : "rgba(214,178,108,.2)"),
              background: tab === s.id ? "rgba(214,178,108,.16)" : "transparent",
              color: tab === s.id ? "var(--text-candlelight)" : "var(--text-muted)",
              boxShadow: tab === s.id ? "0 0 16px -5px rgba(214,178,108,.55)" : "none",
              transition: "all var(--dur-fast) var(--ease-quiet)",
            }}>{s.label}</button>
          ))}
        </div>
        <div style={{ maxWidth: 720 }}><View /></div>
      </div>
    </div>
  );
}

window.Screens = Screens;

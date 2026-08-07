/* App — The Clockwork Dark: World & Interface.
   A grim-dark interactive bible: places, souls, things, the HUD, and
   the live playable scene. Ash & Thorn throughout. Sections are
   registered on window by their own files. */

const { useState: useAppState } = React;

const TABS = [
  { id: "atlas", label: "Atlas", sub: "Places & buildings" },
  { id: "souls", label: "Souls", sub: "Characters, the cat, the wizard" },
  { id: "things", label: "Things", sub: "Items & relics" },
  { id: "interface", label: "Interface", sub: "HUD & panel design" },
  { id: "screens", label: "Screens", sub: "Trade · Bakery · Millhaven" },
  { id: "play", label: "Play", sub: "The live scene" },
];

function NavItem({ tab, active, onClick }) {
  return (
    <button onClick={onClick} style={{
      display: "block", width: "100%", textAlign: "left", cursor: "pointer",
      padding: "11px 16px", border: "none", borderLeft: "3px solid " + (active ? "var(--accent-candle)" : "transparent"),
      background: active ? "linear-gradient(90deg, rgba(214,178,108,.14), transparent)" : "transparent",
      transition: "all var(--dur-fast) var(--ease-quiet)",
    }}
      onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = "rgba(255,255,255,.03)"; }}
      onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = "transparent"; }}>
      <span style={{ display: "block", fontFamily: "var(--font-ui)", fontSize: "var(--text-base)", fontWeight: 600,
        letterSpacing: ".02em", color: active ? "var(--text-candlelight)" : "var(--text-on-dark)" }}>{tab.label}</span>
      <span style={{ display: "block", fontFamily: "var(--font-ui)", fontSize: "var(--text-xs)",
        color: "var(--text-muted)", marginTop: 2 }}>{tab.sub}</span>
    </button>
  );
}

function App() {
  const [tab, setTab] = useAppState("atlas");
  const Section = {
    atlas: window.Atlas, souls: window.Souls, things: window.Things,
    interface: window.InterfaceKit, screens: window.Screens, play: window.PlaySection,
  }[tab];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "248px 1fr", height: "100vh", minHeight: 0,
      background: "radial-gradient(120% 100% at 50% 0%, #10161a, #050807 72%)", color: "var(--text-on-dark)" }}>
      {/* sidebar */}
      <aside style={{ display: "flex", flexDirection: "column", minHeight: 0,
        background: "linear-gradient(180deg,#090d0e,#060908)", borderRight: "1px solid rgba(214,178,108,.16)",
        boxShadow: "inset -20px 0 40px -30px #000" }}>
        <div style={{ padding: "20px 16px 16px", borderBottom: "1px solid rgba(214,178,108,.12)" }}>
          <img src="../../assets/wordmark.svg" alt="The Clockwork Dark" style={{ width: 196, filter: "drop-shadow(0 2px 10px rgba(0,0,0,.6))" }} />
          <p style={{ margin: "12px 2px 0", fontFamily: "var(--font-narration)", fontStyle: "italic",
            fontSize: "var(--text-sm)", color: "rgba(214,178,108,.6)" }}>World &amp; interface bible</p>
        </div>
        <nav style={{ padding: "10px 0", flex: 1, overflowY: "auto" }}>
          {TABS.map((t) => <NavItem key={t.id} tab={t} active={tab === t.id} onClick={() => setTab(t.id)} />)}
        </nav>
        <div style={{ padding: "14px 16px", borderTop: "1px solid rgba(214,178,108,.12)",
          fontFamily: "var(--font-mono)", fontSize: "10px", letterSpacing: ".06em",
          textTransform: "uppercase", color: "var(--text-muted)", lineHeight: 1.7 }}>
          <div>Hearth Ledger · Ash &amp; Thorn</div>
          <div style={{ color: "rgba(214,178,108,.5)" }}>v0.1 · grim-dark</div>
        </div>
      </aside>

      {/* content */}
      <main style={{ minHeight: 0, overflowY: tab === "play" ? "hidden" : "auto", position: "relative" }}>
        {Section ? <Section /> : <div style={{ padding: 40 }}>Loading…</div>}
      </main>
    </div>
  );
}

window.CWApp = App;

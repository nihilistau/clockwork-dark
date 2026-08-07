/* Atlas — places & buildings of the Heartlands' margin. */

function PlaceCard({ p }) {
  return (
    <article style={{ background: "linear-gradient(180deg,#0e1311,#0a0d0b)",
      border: "1px solid rgba(214,178,108,.14)", borderRadius: "var(--radius-sm)", overflow: "hidden",
      boxShadow: "0 14px 34px -16px rgba(0,0,0,.8)" }}>
      <PaintFrame tint={p.tint} glow={p.glow} caption={p.caption} corrupted={p.corrupted} ratio="16/9" />
      <div style={{ padding: "16px 18px 18px" }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10 }}>
          <h3 style={{ margin: 0, fontFamily: "var(--font-narration)", fontSize: "var(--text-xl)",
            fontWeight: 500, color: "var(--text-on-dark)" }}>{p.name}</h3>
          <Pill brass>{p.kind}</Pill>
        </div>
        <p style={{ margin: "9px 0 0", fontFamily: "var(--font-narration)", fontSize: "var(--text-base)",
          lineHeight: 1.5, color: "rgba(226,220,201,.7)" }}>{p.blurb}</p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
          {p.times.map((t) => <Pill key={t}>{t}</Pill>)}
        </div>
        <Prompt>{p.prompt}</Prompt>
        <p style={{ margin: "10px 0 0", fontFamily: "var(--font-ui)", fontSize: "var(--text-xs)",
          fontStyle: "italic", color: "var(--text-muted)" }}>{p.note}</p>
      </div>
    </article>
  );
}

function Atlas() {
  const places = window.CW_DATA.places;
  const weather = window.CW_DATA.weather;
  return (
    <div>
      <SectionHead kicker="The Atlas" title="Places & buildings"
        lede="A frontier village at the edge of an old forest. Beauty in bread steam and moss; dread at the margin where the wheat turns wrong. Every location is a ComfyUI 16:9 still — no characters centre-frame." />
      <div style={{ padding: "26px 40px 40px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))", gap: 22 }}>
          {places.map((p) => <PlaceCard key={p.id} p={p} />)}
        </div>

        <div style={{ marginTop: 38 }}>
          <Kicker>Weather — footer state &amp; image modifier</Kicker>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            {weather.map((w) => (
              <div key={w.key} style={{ flex: "1 1 150px", minWidth: 150, padding: "14px 16px",
                borderRadius: "var(--radius-sm)", background: w.corrupted ? "rgba(122,158,79,.08)" : "rgba(255,255,255,.03)",
                border: "1px solid " + (w.corrupted ? "rgba(122,158,79,.3)" : "rgba(214,178,108,.16)") }}>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)",
                  color: w.corrupted ? "var(--corruption)" : "var(--text-candlelight)", textTransform: "uppercase", letterSpacing: ".06em" }}>{w.label}</div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: "var(--text-xs)", color: "var(--text-muted)", marginTop: 5 }}>{w.note}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

window.Atlas = Atlas;

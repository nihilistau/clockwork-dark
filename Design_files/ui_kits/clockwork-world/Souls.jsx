/* Souls — the people, the cat, and the Assistant's many faces. */

function NpcCard({ n }) {
  return (
    <article style={{ background: "linear-gradient(180deg,#0e1311,#0a0d0b)",
      border: "1px solid rgba(214,178,108,.14)", borderRadius: "var(--radius-sm)", overflow: "hidden",
      boxShadow: "0 14px 34px -16px rgba(0,0,0,.8)" }}>
      <div style={{ position: "relative" }}>
        <PaintFrame tint={n.tint} sil={n.sil} accent={n.accent} robe="#2a2a22" ratio="4/3" caption={n.role} />
        {n.ambiguous && <span style={{ position: "absolute", top: 8, left: 10, fontFamily: "var(--font-mono)",
          fontSize: 9, letterSpacing: ".1em", textTransform: "uppercase", color: "rgba(214,178,108,.7)",
          background: "rgba(16,16,12,.6)", padding: "2px 6px", borderRadius: 3 }}>ambiguous</span>}
      </div>
      <div style={{ padding: "14px 16px 16px" }}>
        <h3 style={{ margin: 0, fontFamily: "var(--font-narration)", fontSize: "var(--text-lg)",
          fontWeight: 500, color: "var(--text-on-dark)" }}>{n.name}</h3>
        <p style={{ margin: "3px 0 0", fontFamily: "var(--font-ui)", fontSize: "var(--text-xs)",
          textTransform: "uppercase", letterSpacing: ".06em", color: "var(--accent-brass)" }}>{n.mood}</p>
        <p style={{ margin: "9px 0 0", fontFamily: "var(--font-narration)", fontSize: "var(--text-base)",
          lineHeight: 1.5, color: "rgba(226,220,201,.7)" }}>{n.blurb}</p>
        <p style={{ margin: "10px 0 0", fontFamily: "var(--font-mono)", fontSize: "11px",
          color: "var(--text-muted)" }}><span style={{ color: "var(--accent-brass)", textTransform: "uppercase", letterSpacing: ".08em" }}>Voice</span> · {n.voice}</p>
      </div>
    </article>
  );
}

function RobePanel({ r }) {
  return (
    <div style={{ borderRadius: "var(--radius-sm)", overflow: "hidden",
      border: "1px solid rgba(214,178,108,.16)", boxShadow: "0 14px 34px -16px rgba(0,0,0,.85)" }}>
      <div style={{ position: "relative", height: 220,
        background: `radial-gradient(80% 60% at 50% 16%, rgba(214,178,108,.18), transparent 58%), linear-gradient(180deg, #0c0f0d, #07090800)` }}>
        <PaintFrame tint="linear-gradient(180deg,#0c100e,#070908)" sil="wizard" robe={r.hex} accent={r.trim} height={220} />
        <span style={{ position: "absolute", top: 9, left: 11, fontFamily: "var(--font-mono)", fontSize: 9,
          letterSpacing: ".1em", textTransform: "uppercase", color: "rgba(214,178,108,.7)",
          background: "rgba(12,12,9,.6)", padding: "2px 7px", borderRadius: 3 }}>{r.phase}</span>
      </div>
      <div style={{ padding: "14px 16px 16px", background: "linear-gradient(180deg,#0e1311,#0a0d0b)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <span style={{ width: 16, height: 16, borderRadius: "50%", background: r.hex,
            boxShadow: "0 0 0 1px rgba(255,255,255,.12), 0 0 10px " + r.hex }} />
          <h3 style={{ margin: 0, fontFamily: "var(--font-narration)", fontSize: "var(--text-lg)",
            fontWeight: 500, color: "var(--text-on-dark)" }}>{r.name}</h3>
        </div>
        <p style={{ margin: "8px 0 0", fontFamily: "var(--font-ui)", fontSize: "var(--text-xs)",
          textTransform: "uppercase", letterSpacing: ".06em", color: "var(--accent-brass)" }}>{r.reads}</p>
        <p style={{ margin: "8px 0 0", fontFamily: "var(--font-narration)", fontSize: "var(--text-base)",
          lineHeight: 1.5, color: "rgba(226,220,201,.7)" }}>{r.blurb}</p>
      </div>
    </div>
  );
}

function FormChip({ f }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ width: "100%", aspectRatio: "1/1", borderRadius: "var(--radius-sm)", overflow: "hidden",
        border: "1px solid rgba(214,178,108,.16)", position: "relative" }}>
        <PaintFrame tint="linear-gradient(180deg,#0e1311,#070908)" sil={f.sil} robe={f.robe} accent="#d6b26c" height={120} />
      </div>
      <div style={{ marginTop: 8, fontFamily: "var(--font-ui)", fontSize: "var(--text-sm)", fontWeight: 600,
        textTransform: "uppercase", letterSpacing: ".06em", color: "var(--text-candlelight)" }}>{f.form}</div>
      <div style={{ fontFamily: "var(--font-ui)", fontSize: "11px", color: "var(--text-muted)", marginTop: 2 }}>{f.when}</div>
      <div style={{ fontFamily: "var(--font-narration)", fontStyle: "italic", fontSize: "12px", color: "rgba(226,220,201,.6)", marginTop: 4 }}>{f.note}</div>
    </div>
  );
}

function Souls() {
  const D = window.CW_DATA;
  return (
    <div>
      <SectionHead kicker="The Souls" title="Characters & the Assistant"
        lede="Edgewood is poor but proud — frontier means mixed travelers, drawn with respect, never caricature. And the Assistant is never a tutorial fairy: it begins as a cat and grows into something robed and certain." />
      <div style={{ padding: "26px 40px 40px" }}>

        <Kicker>Villagers &amp; the cat — portrait briefs (3:4)</Kicker>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 20 }}>
          {D.npcs.map((n) => <NpcCard key={n.id} n={n} />)}
        </div>

        {/* The robed wizard — the centrepiece */}
        <div style={{ marginTop: 44, padding: "26px 28px", borderRadius: "var(--radius-md)",
          background: "radial-gradient(90% 100% at 50% 0%, rgba(190,118,58,.08), transparent 60%), linear-gradient(180deg,#0c100e,#080a09)",
          border: "1px solid rgba(214,178,108,.16)" }}>
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
            <h2 style={{ margin: 0, fontFamily: "var(--font-narration)", fontSize: "var(--text-2xl)",
              fontWeight: 500, color: "var(--text-on-dark)" }}>The Assistant Wizard — robe study</h2>
            <p style={{ margin: 0, maxWidth: 420, fontFamily: "var(--font-narration)", fontStyle: "italic",
              fontSize: "var(--text-base)", color: "rgba(214,178,108,.7)" }}>
              The hooded form's robe reads its intent. White mercy → grey watching → red appetite → black the Clockwork Dark itself.</p>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 18, marginTop: 22 }}>
            {D.robes.map((r) => <RobePanel key={r.key} r={r} />)}
          </div>
        </div>

        {/* Five canonical forms */}
        <div style={{ marginTop: 40 }}>
          <Kicker>The five canonical forms</Kicker>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 16 }}>
            {D.assistantForms.map((f) => <FormChip key={f.form} f={f} />)}
          </div>
        </div>

        {/* Player archetypes */}
        <div style={{ marginTop: 40 }}>
          <Kicker>Player archetypes — silhouette, not class</Kicker>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 18 }}>
            {D.archetypes.map((a) => (
              <div key={a.id} style={{ display: "flex", gap: 14, padding: "14px 16px", borderRadius: "var(--radius-sm)",
                background: "linear-gradient(180deg,#0e1311,#0a0d0b)", border: "1px solid rgba(214,178,108,.14)" }}>
                <div style={{ width: 64, flex: "none", borderRadius: 3, overflow: "hidden", border: "1px solid rgba(214,178,108,.14)" }}>
                  <PaintFrame tint={a.tint} sil="person" robe="#2a2a20" accent="#d6b26c" height={84} />
                </div>
                <div>
                  <h3 style={{ margin: 0, fontFamily: "var(--font-narration)", fontSize: "var(--text-lg)", fontWeight: 500, color: "var(--text-on-dark)" }}>{a.name}</h3>
                  <p style={{ margin: "4px 0 0", fontFamily: "var(--font-ui)", fontSize: "var(--text-xs)", color: "var(--accent-brass)" }}>{a.gear}</p>
                  <p style={{ margin: "5px 0 0", fontFamily: "var(--font-narration)", fontSize: "13px", color: "rgba(226,220,201,.65)" }}>{a.look}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

window.Souls = Souls;

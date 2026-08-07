/* Things — items, tools, wards, and the wrong relics. */

function ItemTile({ it }) {
  return (
    <div style={{ borderRadius: "var(--radius-sm)", overflow: "hidden",
      border: "1px solid " + (it.corrupted ? "rgba(122,158,79,.3)" : "rgba(214,178,108,.14)"),
      background: "linear-gradient(180deg,#0e1311,#0a0d0b)", boxShadow: "0 10px 26px -14px rgba(0,0,0,.8)" }}>
      <div style={{ position: "relative", height: 96,
        background: `radial-gradient(70% 80% at 50% 30%, ${hexA(it.tint, .9)}, ${hexA(it.tint, .25)} 70%, #0a0d0b)`,
        display: "grid", placeItems: "center" }}>
        {/* item silhouette: a soft painterly lozenge tinted by the item */}
        <div style={{ width: 46, height: 46, borderRadius: it.brass ? "50%" : "30% 30% 36% 36%",
          background: `linear-gradient(160deg, ${it.tint}, rgba(0,0,0,.5))`,
          boxShadow: "inset 0 1px 3px rgba(255,255,255,.2), 0 4px 10px rgba(0,0,0,.5)",
          border: it.brass ? "1px solid rgba(214,178,108,.5)" : "1px solid rgba(0,0,0,.3)" }} />
        <div style={{ position: "absolute", inset: 0, backgroundImage: "var(--texture-paper)", opacity: .4, mixBlendMode: "multiply" }} />
        <div style={{ position: "absolute", inset: 0, boxShadow: "inset 0 0 30px rgba(8,9,6,.7)" }} />
        {it.corrupted && <div style={{ position: "absolute", inset: 0, background: "var(--corruption)", opacity: .12, mixBlendMode: "color" }} />}
        <span style={{ position: "absolute", top: 6, right: 7, fontFamily: "var(--font-mono)", fontSize: 9,
          color: it.corrupted ? "var(--corruption)" : "rgba(214,178,108,.6)", textTransform: "uppercase", letterSpacing: ".06em" }}>{it.tag}</span>
      </div>
      <div style={{ padding: "10px 12px 12px" }}>
        <div style={{ fontFamily: "var(--font-ui)", fontSize: "var(--text-sm)", fontWeight: 600, color: "var(--text-on-dark)" }}>{it.name}</div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginTop: 5 }}>
          <span style={{ fontFamily: "var(--font-ui)", fontSize: "11px", color: "var(--text-muted)" }}>{it.from}</span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: "12px",
            color: it.price === "—" ? "var(--text-muted)" : "var(--text-candlelight)" }}>{it.price}</span>
        </div>
      </div>
    </div>
  );
}

function hexA(hex, a) {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

function Things() {
  const items = window.CW_DATA.items;
  const groups = ["Food", "Forage", "Material", "Tool", "Knowledge", "Ward", "Light", "Apparel", "Craft", "Quest", "Wrong"];
  const used = groups.filter((g) => items.some((i) => i.tag === g));
  return (
    <div>
      <SectionHead kicker="The Things" title="Items & relics"
        lede="Honest names, copper prices — never gold coins floating in the air. Item icons are flat 1:1 illustrations. The 'wrong' relics carry brass where brass should not be." />
      <div style={{ padding: "26px 40px 40px" }}>
        {used.map((g) => (
          <div key={g} style={{ marginBottom: 30 }}>
            <Kicker>{g === "Wrong" ? "Wrong — corruption relics (gated)" : g}</Kicker>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(168px, 1fr))", gap: 16 }}>
              {items.filter((i) => i.tag === g).map((it) => <ItemTile key={it.name} it={it} />)}
            </div>
          </div>
        ))}
        <p style={{ marginTop: 8, fontFamily: "var(--font-narration)", fontStyle: "italic",
          fontSize: "var(--text-base)", color: "rgba(214,178,108,.6)" }}>
          Prices in copper · gold = 100 copper display. Seeds for each icon live in assets/comfyui-prompts.md.</p>
      </div>
    </div>
  );
}

window.Things = Things;

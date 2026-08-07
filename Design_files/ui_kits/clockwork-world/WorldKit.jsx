/* Shared presentational helpers for the world bible — all grim-dark. */

function SectionHead({ kicker, title, lede }) {
  return (
    <header style={{ padding: "34px 40px 18px", borderBottom: "1px solid rgba(214,178,108,.12)",
      position: "relative" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <img src="../../assets/gear-motif.svg" alt="" style={{ width: 20, filter: "brightness(1.4) drop-shadow(0 0 10px rgba(190,118,58,.5))" }} />
        <span style={{ fontFamily: "var(--font-ui)", fontSize: "var(--text-xs)", fontWeight: 700,
          textTransform: "uppercase", letterSpacing: "var(--tracking-title)", color: "var(--accent-brass)" }}>{kicker}</span>
      </div>
      <h1 style={{ margin: 0, fontFamily: "var(--font-narration)", fontSize: "var(--text-3xl)",
        fontWeight: 500, color: "var(--text-on-dark)", letterSpacing: "-.01em", lineHeight: 1.05 }}>{title}</h1>
      {lede && <p style={{ margin: "12px 0 0", maxWidth: 640, fontFamily: "var(--font-narration)",
        fontSize: "var(--text-lg)", lineHeight: var_relaxed, color: "rgba(226,220,201,.72)" }}>{lede}</p>}
    </header>
  );
}
const var_relaxed = "var(--leading-relaxed)";

function Kicker({ children }) {
  return <p style={{ margin: "0 0 14px", fontFamily: "var(--font-ui)", fontSize: "var(--text-xs)",
    fontWeight: 700, textTransform: "uppercase", letterSpacing: "var(--tracking-label)",
    color: "var(--accent-brass)" }}>{children}</p>;
}

function Prompt({ children, neg }) {
  return (
    <div style={{ marginTop: 10, padding: "8px 11px", borderRadius: "var(--radius-sm)",
      background: "rgba(0,0,0,.32)", border: "1px solid rgba(214,178,108,.14)" }}>
      <span style={{ display: "block", fontFamily: "var(--font-mono)", fontSize: "10px",
        textTransform: "uppercase", letterSpacing: ".1em", color: "var(--accent-brass)", marginBottom: 3 }}>
        {neg ? "negative" : "ComfyUI prompt"}
      </span>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", lineHeight: 1.5,
        color: "rgba(214,206,184,.78)" }}>{children}</span>
    </div>
  );
}

function Pill({ children, brass }) {
  return <span style={{ display: "inline-block", fontFamily: "var(--font-ui)", fontSize: "11px",
    padding: "2px 8px", borderRadius: "999px", letterSpacing: ".02em",
    color: brass ? "#14140f" : "rgba(226,220,201,.7)",
    background: brass ? "var(--accent-candle)" : "rgba(255,255,255,.05)",
    border: brass ? "none" : "1px solid rgba(214,178,108,.18)" }}>{children}</span>;
}

Object.assign(window, { SectionHead, Kicker, Prompt, Pill });

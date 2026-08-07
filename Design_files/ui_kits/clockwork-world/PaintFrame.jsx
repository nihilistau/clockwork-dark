/* PaintFrame — a painterly placeholder frame standing in for ComfyUI art.
   Layered earth-gradient + candle bloom + paper grain + an abstract
   CSS silhouette. NOT final art: production stills are generated from
   the prompts shown beside each frame. Keeps everything honest while
   giving each subject a distinct, recognisable mood. */

const { useState: _useState } = React;

function Silhouette({ kind, robe = "#5a6a4a", accent = "#e8c47a", scale = 1 }) {
  const base = { position: "absolute", left: "50%", transform: "translateX(-50%)" };
  const eye = (left) => ({
    position: "absolute", top: 0, left, width: 6 * scale, height: 6 * scale,
    borderRadius: "50%", background: accent, boxShadow: `0 0 ${8 * scale}px ${accent}`,
  });

  if (kind === "cat") {
    return (
      <div style={{ position: "absolute", inset: 0 }}>
        {/* body */}
        <div style={{ ...base, bottom: "8%", width: 120 * scale, height: 90 * scale,
          background: robe, borderRadius: "46% 46% 40% 40% / 60% 60% 40% 40%", filter: "blur(0.4px)" }} />
        {/* ears */}
        <div style={{ ...base, bottom: "44%", marginLeft: -34 * scale, width: 0, height: 0,
          borderLeft: `${14 * scale}px solid transparent`, borderRight: `${10 * scale}px solid transparent`,
          borderBottom: `${26 * scale}px solid ${robe}` }} />
        <div style={{ ...base, bottom: "44%", marginLeft: 34 * scale, width: 0, height: 0,
          borderLeft: `${10 * scale}px solid transparent`, borderRight: `${14 * scale}px solid transparent`,
          borderBottom: `${26 * scale}px solid ${robe}` }} />
        {/* head */}
        <div style={{ ...base, bottom: "30%", width: 76 * scale, height: 64 * scale,
          background: robe, borderRadius: "48% 48% 46% 46%" }} />
        {/* tail */}
        <div style={{ position: "absolute", bottom: "10%", right: "20%", width: 60 * scale, height: 16 * scale,
          background: robe, borderRadius: "50%", transform: "rotate(-28deg)" }} />
        {/* eyes */}
        <div style={{ ...base, bottom: "40%", width: 40 * scale, height: 6 * scale }}>
          <div style={eye(2)} /><div style={eye(32 * scale)} />
        </div>
      </div>
    );
  }

  if (kind === "hood" || kind === "wizard") {
    return (
      <div style={{ position: "absolute", inset: 0 }}>
        {/* robe body */}
        <div style={{ ...base, bottom: 0, width: 150 * scale, height: 170 * scale,
          background: `linear-gradient(180deg, ${robe} 0%, rgba(0,0,0,.55) 120%)`,
          borderRadius: "44% 44% 12% 12% / 70% 70% 12% 12%" }} />
        {/* hood */}
        <div style={{ ...base, bottom: "44%", width: 104 * scale, height: 116 * scale,
          background: robe, borderRadius: "50% 50% 38% 38% / 62% 62% 40% 40%" }} />
        {/* shadowed face */}
        <div style={{ ...base, bottom: "52%", width: 52 * scale, height: 64 * scale,
          background: "radial-gradient(circle at 50% 40%, #0d100c, #14140f)", borderRadius: "50% 50% 46% 46%" }} />
        {/* eyes in shadow */}
        <div style={{ ...base, bottom: "64%", width: 34 * scale, height: 6 * scale }}>
          <div style={eye(0)} /><div style={eye(28 * scale)} />
        </div>
      </div>
    );
  }

  if (kind === "mirror") {
    return (
      <div style={{ position: "absolute", inset: 0 }}>
        <Silhouette kind="person" robe={robe} accent={accent} scale={scale * 0.82} />
        <div style={{ position: "absolute", inset: 0, top: "62%", transform: "scaleY(-1)", opacity: 0.4,
          maskImage: "linear-gradient(180deg, transparent, #000 80%)",
          WebkitMaskImage: "linear-gradient(180deg, transparent, #000 80%)" }}>
          <Silhouette kind="person" robe={accent} accent={robe} scale={scale * 0.82} />
        </div>
      </div>
    );
  }

  // person / child
  const s = kind === "child" ? scale * 0.72 : scale;
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      {/* shoulders */}
      <div style={{ ...base, bottom: 0, width: 150 * s, height: 130 * s,
        background: `linear-gradient(180deg, ${robe} 0%, rgba(0,0,0,.5) 130%)`,
        borderRadius: "46% 46% 16% 16% / 64% 64% 16% 16%" }} />
      {/* head */}
      <div style={{ ...base, bottom: "46%", width: 72 * s, height: 86 * s,
        background: robe, borderRadius: "48% 48% 44% 44%" }} />
      {/* face shadow hint */}
      <div style={{ ...base, bottom: "50%", width: 50 * s, height: 60 * s,
        background: "radial-gradient(circle at 50% 38%, rgba(0,0,0,.28), transparent 70%)", borderRadius: "50%" }} />
    </div>
  );
}

function PaintFrame({ tint, glow, caption, sil, robe, accent, corrupted, ratio = "16/9", height, children }) {
  return (
    <div style={{
      position: "relative", width: "100%", aspectRatio: height ? undefined : ratio,
      height: height || undefined, overflow: "hidden",
      background: tint || "var(--surface-scene)",
      border: "var(--border-rule) solid var(--iron-900)",
      boxShadow: "var(--shadow-card)",
    }}>
      {glow && <div className="cw-flicker" style={{ position: "absolute", inset: 0, background: glow, mixBlendMode: "screen" }} />}
      {/* atmospheric depth — low mist band */}
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: "42%",
        background: "linear-gradient(0deg, rgba(160,150,120,.10), transparent)", mixBlendMode: "screen" }} />
      {sil && (
        <React.Fragment>
          {/* ground contact shadow */}
          <div style={{ position: "absolute", left: "50%", bottom: "5%", width: "46%", height: 16,
            transform: "translateX(-50%)", borderRadius: "50%",
            background: "radial-gradient(closest-side, rgba(0,0,0,.55), transparent)", filter: "blur(2px)" }} />
          {/* rim-lit figure */}
          <div style={{ position: "absolute", inset: 0,
            filter: `drop-shadow(0 0 1px ${accent || "#d6b26c"}) drop-shadow(0 0 9px ${hexShadow(accent)})` }}>
            <Silhouette kind={sil} robe={robe} accent={accent} />
          </div>
        </React.Fragment>
      )}
      {/* volumetric light ray from above */}
      <div style={{ position: "absolute", top: "-10%", left: "30%", width: "40%", height: "85%",
        background: "linear-gradient(180deg, rgba(214,178,108,.12), transparent 72%)",
        transform: "skewX(-9deg)", mixBlendMode: "screen", pointerEvents: "none" }} />
      {corrupted && <div style={{ position: "absolute", inset: 0, background: "var(--corruption)", opacity: 0.16, mixBlendMode: "color" }} />}
      {/* paper / oil grain */}
      <div style={{ position: "absolute", inset: 0, backgroundImage: "var(--texture-paper)", opacity: 0.55, mixBlendMode: "multiply" }} />
      {/* cinematic vignette */}
      <div style={{ position: "absolute", inset: 0, boxShadow: "inset 0 0 70px 12px rgba(8,9,6,.7)" }} />
      {/* top film lip */}
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 22, background: "linear-gradient(180deg, rgba(6,8,5,.6), transparent)" }} />
      {/* ComfyUI watermark */}
      <span style={{
        position: "absolute", top: 8, right: 10, fontFamily: "var(--font-mono)", fontSize: 10,
        letterSpacing: ".08em", textTransform: "uppercase", color: "rgba(242,232,213,.5)",
      }}>ComfyUI still</span>
      {caption && (
        <span style={{
          position: "absolute", left: 10, bottom: 10, fontFamily: "var(--font-narration)", fontStyle: "italic",
          fontSize: "var(--text-sm)", color: "rgba(242,232,213,.92)", textShadow: "0 1px 3px rgba(0,0,0,.6)",
        }}>{caption}</span>
      )}
      {children}
    </div>
  );
}

window.Silhouette = Silhouette;
window.PaintFrame = PaintFrame;

function hexShadow(hex) {
  if (!hex || hex[0] !== "#") return "rgba(214,178,108,.35)";
  let h = hex.slice(1);
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const n = parseInt(h, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, .35)`;
}

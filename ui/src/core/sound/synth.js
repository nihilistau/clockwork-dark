/** Synth sounds from data (v0.24.0 spec §4.2). Pure Web Audio; no state. */
const STEPS = { C: -9, D: -7, E: -5, F: -4, G: -2, A: 0, B: 2 };

export function noteHz(pitch) {
  if (typeof pitch === "number") return pitch;
  const m = /^([A-G])([#b]?)([0-8])$/.exec(String(pitch));
  if (!m) throw new Error(`not a note: ${pitch}`);
  const semis = STEPS[m[1]] + (m[2] === "#" ? 1 : m[2] === "b" ? -1 : 0) + (Number(m[3]) - 4) * 12;
  return 440 * Math.pow(2, semis / 12);
}

const layerMs = (l) => (l.start_ms || 0) + (l.attack_ms || 0) + (l.decay_ms || 0) + (l.hold_ms || 0) + (l.release_ms ?? 20);

export function durationMs(def) {
  let total = 0;
  if (def.layers) total = Math.max(...def.layers.map(layerMs));
  else if (def.sequence) total = Math.max(...def.sequence.notes.map(([at, , len]) => at + len + (def.sequence.voice.release_ms ?? 20)));
  const rep = def.repeat || { times: 1, gap_ms: 0 };
  return total * rep.times + (rep.gap_ms || 0) * (rep.times - 1);
}

let noise = null;
function noiseBuffer(ctx) {
  if (noise && noise.sampleRate === ctx.sampleRate) return noise;
  noise = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
  const data = noise.getChannelData(0);
  for (let i = 0; i < data.length; i += 1) data[i] = Math.random() * 2 - 1;
  return noise;
}

function voice(ctx, layer, out, t0, freq, lengthMs, cents, sources) {
  const s = t0 + (layer.start_ms || 0) / 1000;
  const a = (layer.attack_ms || 0) / 1000;
  const d = (layer.decay_ms || 0) / 1000;
  const h = lengthMs != null ? Math.max(0, lengthMs / 1000 - a - d) : (layer.hold_ms || 0) / 1000;
  const r = (layer.release_ms ?? 20) / 1000;
  const peak = layer.gain ?? 1;
  const sus = (layer.sustain ?? 0) * peak;
  const env = ctx.createGain();
  env.gain.setValueAtTime(0, s);
  env.gain.linearRampToValueAtTime(peak, s + a);
  env.gain.linearRampToValueAtTime(sus, s + a + d);
  env.gain.setValueAtTime(sus, s + a + d + h);
  env.gain.linearRampToValueAtTime(0, s + a + d + h + r);
  let src;
  if (layer.wave === "noise") {
    src = ctx.createBufferSource();
    src.buffer = noiseBuffer(ctx);
  } else {
    src = ctx.createOscillator();
    src.type = layer.wave;
    src.frequency.setValueAtTime(freq, s);
    if (layer.to) src.frequency.exponentialRampToValueAtTime(layer.to, s + (layer.glide_ms || 0) / 1000);
    src.detune.setValueAtTime((layer.detune || 0) + cents, s);
  }
  let head = src;
  if (layer.filter) {
    const f = ctx.createBiquadFilter();
    f.type = layer.filter.type;
    f.frequency.setValueAtTime(layer.filter.freq, s);
    if (layer.filter.to) f.frequency.exponentialRampToValueAtTime(layer.filter.to, s + (layer.filter.glide_ms || 0) / 1000);
    if (layer.filter.q) f.Q.setValueAtTime(layer.filter.q, s);
    head.connect(f);
    head = f;
  }
  head.connect(env);
  if (layer.tremolo) {
    const lfo = ctx.createOscillator();
    const depth = ctx.createGain();
    lfo.frequency.setValueAtTime(layer.tremolo.rate_hz, s);
    depth.gain.setValueAtTime(layer.tremolo.depth * peak, s);
    lfo.connect(depth);
    depth.connect(env.gain);
    lfo.start(s);
    lfo.stop(s + a + d + h + r);
    sources.push(lfo);
  }
  env.connect(out);
  src.start(s);
  src.stop(s + a + d + h + r + 0.01);
  sources.push(src);
}

/** Schedule `def` on `ctx` into `out` at `when` (seconds). Returns the source nodes (the voice cap stops them). */
export function render(ctx, def, out, when) {
  const sources = [];
  const cents = def.jitter_cents ? (Math.random() * 2 - 1) * def.jitter_cents : 0;
  const rep = def.repeat || { times: 1, gap_ms: 0 };
  const once = durationMs({ ...def, repeat: undefined }) / 1000;
  for (let i = 0; i < rep.times; i += 1) {
    const t0 = when + i * (once + (rep.gap_ms || 0) / 1000);
    if (def.layers) for (const layer of def.layers) voice(ctx, layer, out, t0, layer.freq, null, cents, sources);
    else for (const [at, pitch, len] of def.sequence.notes) {
      voice(ctx, { ...def.sequence.voice, start_ms: at }, out, t0, noteHz(pitch), len, cents, sources);
    }
  }
  return sources;
}

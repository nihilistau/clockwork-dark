// A fake Web Audio: records every node, start/stop, param write and resume. No sound is made.
export function installFakeAudio({ canPlayOgg = "probably", decodeFails = false } = {}) {
  const log = { contexts: [], nodes: [], starts: [], params: [], resumes: 0, decodes: 0, fetches: [] };
  const param = (owner, name) => ({
    value: 0,
    setValueAtTime(v, t) { log.params.push({ owner, name, op: "set", v, t }); this.value = v; return this; },
    linearRampToValueAtTime(v, t) { log.params.push({ owner, name, op: "lin", v, t }); return this; },
    exponentialRampToValueAtTime(v, t) { log.params.push({ owner, name, op: "exp", v, t }); return this; },
    cancelScheduledValues() { return this; },
  });
  const node = (kind, extra = {}) => {
    const n = { kind, connect(to) { n.to = to; return to; }, disconnect() {}, ...extra };
    log.nodes.push(n);
    return n;
  };
  class FakeContext {
    constructor() { this.state = "suspended"; this.currentTime = 0; this.sampleRate = 48000; this.destination = node("destination"); log.contexts.push(this); }
    resume() { log.resumes += 1; this.state = "running"; return Promise.resolve(); }
    createGain() { const n = node("gain"); n.gain = param(n, "gain"); return n; }
    createOscillator() {
      const n = node("osc", { type: "sine", start(t) { log.starts.push({ node: n, t }); }, stop() {} });
      n.frequency = param(n, "frequency"); n.detune = param(n, "detune"); return n;
    }
    createBiquadFilter() { const n = node("filter", { type: "lowpass" }); n.frequency = param(n, "frequency"); n.Q = param(n, "Q"); return n; }
    createBuffer(ch, len, rate) { return { length: len, sampleRate: rate, getChannelData: () => new Float32Array(len) }; }
    createBufferSource() {
      const n = node("buffer", { start(t) { log.starts.push({ node: n, t }); }, stop() {} });
      n.playbackRate = param(n, "playbackRate"); return n;
    }
    decodeAudioData() { log.decodes += 1; return decodeFails ? Promise.reject(new Error("bad")) : Promise.resolve({ duration: 0.2 }); }
  }
  globalThis.AudioContext = FakeContext;
  globalThis.Audio = class { canPlayType() { return canPlayOgg; } };
  globalThis.fetch = async (url) => { log.fetches.push(String(url)); return { ok: true, arrayBuffer: async () => new ArrayBuffer(8) }; };
  return log;
}

export const CATALOG = {
  enabled: true,
  limits: { voices: 8, throttle_ms: 60, roll_degree_delay_ms: 450 },
  events: ["ui.press", "turn.arrive", "roll.cast", "roll.success", "alert.error", "story.door"],
  sounds: {
    "ui.click": { category: "ui", label: "Click", synth: { layers: [{ wave: "square", freq: 2200, to: 1400, glide_ms: 18, attack_ms: 1, decay_ms: 28, gain: 0.18, filter: { type: "lowpass", freq: 5000 } }] } },
    "game.turn": { category: "game", label: "Turn", synth: { layers: [{ wave: "sine", freq: 1046.5, attack_ms: 3, decay_ms: 700, gain: 0.22 }] } },
    "roll.success": { category: "game", label: "Success", synth: { sequence: { voice: { wave: "triangle", attack_ms: 3, decay_ms: 200, gain: 0.25 }, notes: [[0, "C5", 120], [110, "F#5", 220]] } } },
    "alert.error": { category: "alert", label: "Error", essential: true, synth: { repeat: { times: 2, gap_ms: 70 }, layers: [{ wave: "square", freq: 220, decay_ms: 90 }] } },
    "story.door": { category: "world", label: "Door", file: "files/door.ogg", url: "/sound/probe/files/door.ogg", fallback: { layers: [{ wave: "noise", decay_ms: 60, gain: 0.2 }] } },
  },
  bind: { "ui.press": "ui.click", "turn.arrive": "game.turn", "roll.cast": null, "roll.success": "roll.success", "alert.error": "alert.error", "story.door": "story.door" },
};

export const gesture = (type = "pointerdown") => window.dispatchEvent(new Event(type));

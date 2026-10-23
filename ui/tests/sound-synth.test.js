// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { installFakeAudio } from "./helpers/fake-audio.js";
import { durationMs, noteHz, render } from "../src/core/sound/synth.js";

describe("the synth", () => {
  it("names notes", () => {
    expect(noteHz("A4")).toBeCloseTo(440, 3);
    expect(noteHz("F#5")).toBeCloseTo(739.989, 2);
    expect(noteHz("Bb4")).toBeCloseTo(466.164, 2);
    expect(noteHz(523.25)).toBe(523.25);
  });

  it("renders a layer: its wave, frequency, glide and envelope", () => {
    const log = installFakeAudio();
    const ctx = new AudioContext();
    render(ctx, { layers: [{ wave: "square", freq: 2200, to: 1400, glide_ms: 18, attack_ms: 1, decay_ms: 28, gain: 0.5, filter: { type: "lowpass", freq: 5000 } }] }, ctx.destination, 0);
    const osc = log.nodes.find((n) => n.kind === "osc");
    expect(osc.type).toBe("square");
    expect(log.params.find((p) => p.owner === osc && p.name === "frequency" && p.op === "set").v).toBe(2200);
    expect(log.params.find((p) => p.owner === osc && p.name === "frequency" && p.op === "exp").v).toBe(1400);
    expect(log.nodes.find((n) => n.kind === "filter").type).toBe("lowpass");
    const env = log.params.filter((p) => p.name === "gain" && p.op === "lin");
    expect(env[0].v).toBeCloseTo(0.5);
    expect(env[0].t).toBeCloseTo(0.001);
  });

  it("renders a sequence's notes at their times, and repeats", () => {
    const log = installFakeAudio();
    const ctx = new AudioContext();
    render(ctx, { repeat: { times: 2, gap_ms: 100 }, sequence: { voice: { wave: "triangle", decay_ms: 50 }, notes: [[0, "C5", 100], [150, "E5", 100]] } }, ctx.destination, 0);
    expect(log.starts.map((s) => Number(s.t.toFixed(3)))).toEqual([0, 0.15, 0.37, 0.52]);
  });

  it("measures a sound as the server does", () => {
    expect(durationMs({ layers: [{ wave: "sine", freq: 440, start_ms: 10, attack_ms: 5, decay_ms: 100 }] })).toBe(135);
    expect(durationMs({ repeat: { times: 2, gap_ms: 70 }, layers: [{ wave: "square", freq: 220, decay_ms: 90 }] })).toBe(290);
  });
});

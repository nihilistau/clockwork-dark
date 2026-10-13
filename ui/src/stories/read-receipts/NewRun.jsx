/**
 * Setting up the phone (spec §3, §18.1-18.2's `NewRun`): the creation form
 * as a wizard of four steps -- you, looks, interests, what you want.
 *
 * THE FORM IS DATA. It comes from `GET /api/social/creation`
 * (`fetchCreation`) and every field it declares is rendered by its `kind`;
 * the steps only say where the fields this story ships go, and any field no
 * step names (a story's own addition) lands on the last step rather than
 * being lost. Validation mirrors the form's `min`/`max` client-side, and the
 * server's refusal (a 400 naming the field, `"age: must be at least 18"`)
 * is shown under that field, on its step.
 *
 * ONE NAME. `creation.name` is the story's name for the player, and core
 * starts the run with it as `player_name` too (App.jsx `onBegin`); the
 * engine seeds this field's default from a new game's `player_name` when a
 * caller sends no creation name (engine/social/creation.py).
 */
import React, { useEffect, useMemo, useState } from "react";

import { fetchCreation } from "@core/api.js";

import { humanize } from "./phone/format.js";

/** Where each shipped field goes. Unnamed fields join the last step. */
export const STEPS = [
  { id: "you", title: "You", fields: ["name", "sex", "age", "neighbourhood", "attributes.job"] },
  { id: "looks", title: "Looks", fields: ["attributes.height", "attributes.build", "attributes.hair", "attributes.style", "photos"] },
  { id: "interests", title: "Interests", fields: ["hobbies", "personality", "attributes.drinks", "attributes.smokes"] },
  {
    id: "want",
    title: "What you want",
    fields: ["looking_for", "attributes.kids", "discovery.age_min", "discovery.age_max", "discovery.distance"],
  },
];

const LABELS = {
  name: "Your name",
  sex: "You are",
  age: "Age",
  neighbourhood: "Where you live",
  "attributes.job": "Job",
  "attributes.height": "Height",
  "attributes.build": "Build",
  "attributes.hair": "Hair",
  "attributes.style": "Style",
  photos: "Your photos",
  hobbies: "Hobbies",
  personality: "Personality",
  "attributes.drinks": "Drinks",
  "attributes.smokes": "Smokes",
  looking_for: "Looking for",
  "attributes.kids": "Kids",
  "discovery.age_min": "Show me people from age",
  "discovery.age_max": "To age",
  "discovery.distance": "How far",
};

/** Every leaf of the form, `{name: dotted, spec}`, in the form's own order. */
export function leaves(fields, prefix = "") {
  const out = [];
  for (const [key, spec] of Object.entries(fields || {})) {
    const name = `${prefix}${key}`;
    if (spec && typeof spec === "object" && "kind" in spec) out.push({ name, spec });
    else if (spec && typeof spec === "object") out.push(...leaves(spec, `${name}.`));
  }
  return out;
}

/** The steps with the form's leaves placed: named ones where they belong, the rest last. */
export function placed(form) {
  const all = leaves(form);
  const byName = new Map(all.map((leaf) => [leaf.name, leaf]));
  const used = new Set();
  const steps = STEPS.map((step) => ({
    ...step,
    leaves: step.fields.filter((name) => byName.has(name)).map((name) => (used.add(name), byName.get(name))),
  }));
  const rest = all.filter((leaf) => !used.has(leaf.name));
  steps[steps.length - 1].leaves.push(...rest);
  return steps;
}

const optionsOf = (spec) => (spec.of || []).map((row) => (typeof row === "object" ? row : { id: String(row), label: String(row) }));
const optionLabel = (row) => (row.label && row.label !== row.id ? row.label : humanize(row.id));

/** A field's starting value: its default, the middle of a slider, nothing picked otherwise. */
function initialValue(spec) {
  switch (spec.kind) {
    case "text":
      return String(spec.default ?? "");
    case "int":
      return spec.default != null ? String(spec.default) : String(spec.min ?? "");
    case "choice":
      return spec.default != null ? String(spec.default) : "";
    case "multi":
      return [];
    case "sliders": {
      const low = Number(spec.min ?? 1);
      const high = Number(spec.max ?? 5);
      return Object.fromEntries((spec.of || []).map((n) => [typeof n === "object" ? n.id : n, Math.round((low + high) / 2)]));
    }
    default:
      return "";
  }
}

/** The form's `min`/`max`, client-side: "" when the value is acceptable. */
export function problem(spec, value) {
  if (spec.kind === "text") {
    if (spec.max != null && String(value).trim().length > Number(spec.max)) return `At most ${spec.max} characters.`;
    return "";
  }
  if (spec.kind === "int") {
    if (!/^-?\d+$/.test(String(value).trim())) return "A whole number, please.";
    const n = Number(value);
    if (spec.min != null && n < Number(spec.min)) return `At least ${spec.min}.`;
    if (spec.max != null && n > Number(spec.max)) return `At most ${spec.max}.`;
    return "";
  }
  if (spec.kind === "multi") {
    const count = (value || []).length;
    const low = Number(spec.min ?? 0);
    const high = spec.max != null ? Number(spec.max) : Infinity;
    if (count < low) return low === 1 ? "Pick at least one." : `Pick at least ${low}.`;
    if (count > high) return `Pick at most ${high}.`;
  }
  return "";
}

/** The values as the server's `creation` object: nested, with nothing unpicked sent. */
export function creationOf(steps, values) {
  const out = {};
  for (const step of steps) {
    for (const { name, spec } of step.leaves) {
      let value = values[name];
      if (spec.kind === "choice" && value === "") continue; // the engine picks (a seeded default)
      if (spec.kind === "int") value = Number(value);
      if (spec.kind === "text") value = String(value).trim();
      const path = name.split(".");
      let node = out;
      for (const part of path.slice(0, -1)) node = node[part] || (node[part] = {});
      node[path[path.length - 1]] = value;
    }
  }
  return out;
}

/** The server's refusal, `"[Could not begin: ]field.path: reason"`, as {field, message}. */
export function refusalOf(error) {
  const text = String(error || "").replace(/^Could not begin:\s*/, "");
  const match = text.match(/^([a-z_][a-z0-9_.]*):\s*(.+)$/i);
  return match ? { field: match[1], message: match[2] } : text ? { field: "", message: text } : null;
}

function Field({ name, spec, value, onChange, error }) {
  const id = `rr-new-${name.replace(/\./g, "-")}`;
  const label = LABELS[name] || humanize(name.split(".").pop());
  const describe = error ? `${id}-error` : undefined;
  let control;
  if (spec.kind === "text") {
    control = (
      <input id={id} className="rr-input" type="text" value={value} maxLength={spec.max != null ? Number(spec.max) + 20 : undefined}
        aria-describedby={describe} onChange={(e) => onChange(e.target.value)} />
    );
  } else if (spec.kind === "int") {
    control = (
      <input id={id} className="rr-input rr-input--num" type="number" inputMode="numeric" value={value}
        min={spec.min} max={spec.max} aria-describedby={describe} onChange={(e) => onChange(e.target.value)} />
    );
  } else if (spec.kind === "choice") {
    control = (
      <select id={id} className="rr-input" value={value} aria-describedby={describe} onChange={(e) => onChange(e.target.value)}>
        {spec.default == null && <option value="">Surprise me</option>}
        {optionsOf(spec).map((row) => (
          <option key={row.id} value={row.id}>
            {optionLabel(row)}
          </option>
        ))}
      </select>
    );
  } else if (spec.kind === "multi") {
    const picked = new Set(value || []);
    control = (
      <div className="rr-picks" role="group" aria-labelledby={`${id}-label`} aria-describedby={describe}>
        {optionsOf(spec).map((row) => (
          <button
            key={row.id}
            type="button"
            className={`rr-pick${picked.has(row.id) ? " is-on" : ""}`}
            aria-pressed={picked.has(row.id)}
            onClick={() => onChange(picked.has(row.id) ? value.filter((v) => v !== row.id) : [...(value || []), row.id])}
          >
            {optionLabel(row)}
          </button>
        ))}
      </div>
    );
  } else if (spec.kind === "sliders") {
    control = (
      <div className="rr-sliders" role="group" aria-labelledby={`${id}-label`}>
        {Object.entries(value || {}).map(([trait, n]) => (
          <label key={trait} className="rr-slider">
            <span>{humanize(trait)}</span>
            <input type="range" min={spec.min ?? 1} max={spec.max ?? 5} step={1} value={n}
              onChange={(e) => onChange({ ...value, [trait]: Number(e.target.value) })} />
            <span className="rr-slider__n">{n}</span>
          </label>
        ))}
      </div>
    );
  } else {
    control = null;
  }
  const counted = spec.kind === "multi" ? ` (${(value || []).length} of ${spec.min ?? 0}–${spec.max ?? "any"})` : "";
  return (
    <div className="rr-field" data-field={name}>
      {spec.kind === "multi" || spec.kind === "sliders" ? (
        <span className="rr-field__label" id={`${id}-label`}>
          {label}
          {counted}
        </span>
      ) : (
        <label className="rr-field__label" htmlFor={id} id={`${id}-label`}>
          {label}
        </label>
      )}
      {control}
      {error && (
        <p className="rr-field__error" id={`${id}-error`} data-testid={`error-${name}`} role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export default function NewRun({ onBegin, onCancel, busy = false, error = "" }) {
  const [form, setForm] = useState(null);
  const [failed, setFailed] = useState("");
  const [values, setValues] = useState({});
  const [step, setStep] = useState(0);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    let live = true;
    fetchCreation()
      .then((data) => {
        if (!live) return;
        const fields = (data && data.fields) || {};
        setForm(fields);
        setValues(Object.fromEntries(leaves(fields).map(({ name, spec }) => [name, initialValue(spec)])));
      })
      .catch((err) => live && setFailed(err.message || "The form could not be loaded."));
    return () => {
      live = false;
    };
  }, []);

  const steps = useMemo(() => (form ? placed(form) : []), [form]);
  const refused = refusalOf(error);

  // The server's refusal names a field: go to its step.
  useEffect(() => {
    if (!refused || !refused.field || !steps.length) return;
    const at = steps.findIndex((s) => s.leaves.some((leaf) => leaf.name === refused.field || refused.field.startsWith(`${leaf.name}.`)));
    if (at >= 0) setStep(at);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error, steps.length]);

  if (failed) {
    return (
      <main className="rr-new" aria-label="Set up your phone">
        <p className="rr-field__error" role="alert">{failed}</p>
        <button type="button" className="rr-btn rr-btn--quiet" onClick={onCancel}>Back</button>
      </main>
    );
  }
  if (!form) {
    return (
      <main className="rr-new" aria-label="Set up your phone">
        <p className="rr-empty">Loading…</p>
      </main>
    );
  }

  const errors = {};
  for (const s of steps) for (const { name, spec } of s.leaves) {
    const why = problem(spec, values[name]);
    if (why) errors[name] = why;
  }
  const min = values["discovery.age_min"];
  const max = values["discovery.age_max"];
  if (min !== undefined && max !== undefined && !errors["discovery.age_min"] && !errors["discovery.age_max"] && Number(min) > Number(max)) {
    errors["discovery.age_max"] = "Must not be below the youngest age.";
  }
  if (refused && refused.field) {
    const leaf = steps.flatMap((s) => s.leaves).find((l) => l.name === refused.field || refused.field.startsWith(`${l.name}.`));
    errors[leaf ? leaf.name : refused.field] = refused.message;
  }
  const current = steps[step];
  const stepErrors = (s) => s.leaves.filter((leaf) => errors[leaf.name]);
  const clientOnly = (s) => s.leaves.filter((leaf) => problem(leaf.spec, values[leaf.name]) || (leaf.name === "discovery.age_max" && errors[leaf.name] && !(refused && refused.field === leaf.name)));
  const ready = steps.every((s) => clientOnly(s).length === 0);
  const last = step === steps.length - 1;
  const set = (name) => (value) => {
    setTouched(true);
    setValues((v) => ({ ...v, [name]: value }));
  };
  // Show an error once the player has touched something, has reached the
  // last step (where Begin is), or the server said it.
  const shown = (name) => (touched || last || (refused && refused.field) ? errors[name] : "") || "";

  return (
    <main className="rr-new" aria-label="Set up your phone">
      <header className="rr-new__head">
        <h1 className="rr-new__title">Set up your phone</h1>
        <ol className="rr-new__steps">
          {steps.map((s, i) => (
            <li key={s.id} className={`${i === step ? "is-on" : ""}${stepErrors(s).length && (touched || last) ? " has-error" : ""}`}>
              <button type="button" className="rr-new__step" aria-current={i === step ? "step" : undefined} onClick={() => setStep(i)}>
                {s.title}
              </button>
            </li>
          ))}
        </ol>
      </header>
      <section className="rr-new__body" aria-label={current.title}>
        {current.leaves.map(({ name, spec }) => (
          <Field key={name} name={name} spec={spec} value={values[name]} onChange={set(name)} error={shown(name)} />
        ))}
      </section>
      {refused && !refused.field && <p className="rr-field__error" role="alert">{refused.message}</p>}
      {last && !ready && (
        <p className="rr-field__error rr-new__missing" data-testid="still-needed">
          Still needed: {steps.filter((s) => clientOnly(s).length).map((s) => s.title).join(", ")}.
        </p>
      )}
      <footer className="rr-new__foot">
        <button type="button" className="rr-btn rr-btn--quiet" onClick={() => (step === 0 ? onCancel() : setStep(step - 1))}>
          {step === 0 ? "Cancel" : "Back"}
        </button>
        {last ? (
          <button
            type="button"
            className="rr-btn"
            disabled={!ready || busy}
            onClick={() => onBegin(creationOf(steps, values))}
          >
            {busy ? "Starting…" : "Begin"}
          </button>
        ) : (
          <button type="button" className="rr-btn" onClick={() => setStep(step + 1)}>
            Next
          </button>
        )}
      </footer>
    </main>
  );
}

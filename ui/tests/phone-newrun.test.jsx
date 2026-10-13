// @vitest-environment jsdom
// ui/tests/phone-newrun.test.jsx -- READ RECEIPTS' setup wizard (v0.22.0 T27, spec §3, §18.1-18.2).
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import NewRun, { creationOf, placed } from "../src/stories/read-receipts/NewRun.jsx";
import { CREATION_FORM } from "./fixtures/creation.js";
import { button, byTestId, click, mount, typeInto } from "./helpers/dom.js";

let view;
let realFetch;
beforeEach(() => {
  view = mount();
  realFetch = globalThis.fetch;
  globalThis.fetch = vi.fn(async (url) => {
    if (String(url) !== "/api/social/creation") throw new Error(`unexpected fetch ${url}`);
    return { ok: true, json: async () => CREATION_FORM };
  });
});
afterEach(() => {
  view.unmount();
  globalThis.fetch = realFetch;
});

/** Render and let the form's fetch resolve. */
async function open(props = {}) {
  const onBegin = vi.fn();
  const onCancel = vi.fn();
  await React.act(async () => {
    view.render(<NewRun onBegin={onBegin} onCancel={onCancel} busy={false} error="" {...props} />);
  });
  await React.act(async () => {});
  return { onBegin, onCancel };
}

const goTo = (title) => click(button(view.host, title));
const field = (name) => view.host.querySelector(`[data-field="${name}"]`);
const pick = (name, label) => click(button(field(name), label));

describe("the setup wizard", () => {
  it("renders the form it fetched, in four steps, with the name the story gives the player", async () => {
    await open();
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/social/creation");
    const steps = [...view.host.querySelectorAll(".rr-new__step")].map((b) => b.textContent);
    expect(steps).toEqual(["You", "Looks", "Interests", "What you want"]);
    expect(field("name").querySelector("input").value).toBe("Sam");
    expect(field("age").querySelector("input").value).toBe("29");
    // A table field shows the table's own labels.
    expect(field("neighbourhood").textContent).toContain("Harbourside");
  });

  it("places every field of the form, a story's own additions on the last step", () => {
    const form = { ...CREATION_FORM.fields, pets: { kind: "choice", of: [{ id: "cat", label: "cat" }] } };
    const steps = placed(form);
    const names = steps.flatMap((s) => s.leaves.map((l) => l.name));
    expect(names).toHaveLength(new Set(names).size);
    expect(names).toContain("attributes.kids");
    expect(steps[3].leaves.at(-1).name).toBe("pets");
    expect(names).toHaveLength(19 + 1);
  });

  it("keeps Begin disabled under the form's min hobbies, and begins with the creation whole", async () => {
    const { onBegin } = await open();
    goTo("What you want");
    const begin = () => button(view.host, "Begin");
    expect(begin().disabled).toBe(true);
    goTo("Looks");
    pick("photos", "on the harbour wall at sunset");
    goTo("Interests");
    pick("hobbies", "Climbing");
    goTo("What you want");
    expect(begin().disabled).toBe(true); // one hobby of a minimum of two
    goTo("Interests");
    pick("hobbies", "Hiking");
    expect(field("hobbies").textContent).toContain("2 of 2–6");
    goTo("You");
    typeInto(field("name").querySelector("input"), "  Robin ");
    goTo("What you want");
    expect(begin().disabled).toBe(false);
    click(begin());
    const creation = onBegin.mock.calls[0][0];
    expect(creation).toMatchObject({
      name: "Robin", sex: "female", age: 29, hobbies: ["climbing", "hiking"], photos: ["harbour_sunset"],
      looking_for: "unsure", discovery: { age_min: 25, age_max: 38, distance: "city" },
      personality: { outgoing: 3, playful: 3, romantic: 3, adventurous: 3, homebody: 3 },
    });
    // A choice left on "Surprise me" is not sent: the engine draws it from the seed.
    expect(creation).not.toHaveProperty("neighbourhood");
    expect(creation.attributes || {}).not.toHaveProperty("height");
  });

  it("mirrors the form's min and max client-side", async () => {
    await open();
    typeInto(field("age").querySelector("input"), "17");
    expect(field("age").textContent).toContain("At least 18.");
    typeInto(field("age").querySelector("input"), "30");
    expect(field("age").querySelector('[role="alert"]')).toBeNull();
    typeInto(field("name").querySelector("input"), "x".repeat(25));
    expect(field("name").textContent).toContain("At most 24 characters.");
  });

  it("shows the server's 400 under the field it names, on that field's step", async () => {
    await open({ error: "Could not begin: age: must be at least 18" });
    expect(byTestId(view.host, "error-age").textContent).toBe("must be at least 18");
    expect(field("age").contains(byTestId(view.host, "error-age"))).toBe(true);
  });

  it("goes to a refused field on a later step", async () => {
    await open({ error: "Could not begin: discovery.distance: must be one of near, city, anywhere" });
    expect(view.host.querySelector('[aria-current="step"]').textContent).toBe("What you want");
    expect(byTestId(view.host, "error-discovery.distance").textContent).toContain("must be one of");
  });

  it("Cancel leaves for the start screen", async () => {
    const { onCancel } = await open();
    click(button(view.host, "Cancel"));
    expect(onCancel).toHaveBeenCalled();
  });

  it("builds a nested creation from dotted fields, and sends nothing unpicked", () => {
    const steps = placed(CREATION_FORM.fields);
    const values = { name: "Jo", age: "40", sex: "", "discovery.age_min": "20", hobbies: ["a", "b"] };
    expect(creationOf(steps, values)).toMatchObject({ name: "Jo", age: 40, discovery: { age_min: 20 }, hobbies: ["a", "b"] });
    expect(creationOf(steps, values)).not.toHaveProperty("sex");
  });
});

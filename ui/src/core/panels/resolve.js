/**
 * Which panels a story draws, and where (spec §2.2, §2.3).
 *
 * The declaration (`story.panelDeclaration`, the manifest's `ui.panels`,
 * carried raw by the catalogue) or, when omitted, every data-gated panel in
 * its default region, in registry order -- minus `story.ownsPanels`, what the
 * plugin draws itself. A `wanted` panel brings its chip to the header. An id
 * or region the server's validation would refuse is skipped: activation has
 * already failed for such a story, so this is never reached in play, and a
 * client that crashed on it would be the wrong answer anyway.
 */
import { PANELS, REGIONS } from "./registry.js";

const BY_ID = Object.fromEntries(PANELS.map((panel) => [panel.id, panel]));

function picked(declaration) {
  if (declaration === undefined || declaration === null) {
    return PANELS.filter((panel) => panel.gate === "data").map((panel) => ({ panel, region: panel.region }));
  }
  if (!Array.isArray(declaration)) return [];
  const out = [];
  const seen = new Set();
  for (const entry of declaration) {
    const id = typeof entry === "string" ? entry : entry && typeof entry === "object" ? entry.id : null;
    const panel = typeof id === "string" ? BY_ID[id] : undefined;
    if (!panel || seen.has(id)) continue;
    const region = (entry && typeof entry === "object" && entry.region) || panel.region;
    if (!panel.regions.includes(region)) continue;
    seen.add(id);
    out.push({ panel, region });
  }
  return out;
}

export function resolvePanels(story) {
  const owned = new Set(story?.ownsPanels || []);
  const out = Object.fromEntries(REGIONS.map((region) => [region, []]));
  for (const { panel, region } of picked(story?.panelDeclaration)) {
    if (owned.has(panel.id)) continue;
    out[region].push({ id: panel.id, region, Component: panel.Component });
    if (panel.id === "wanted") out.header.push({ id: "wanted-chip", region: "header", Component: panel.Chip || null });
  }
  return out;
}

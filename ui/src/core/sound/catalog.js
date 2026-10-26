import { installCatalog } from "./engine.js";

/** Fetch /api/sounds once per page load and install it (spec §6.1). A failure leaves the page silent, never broken. */
export async function loadCatalog() {
  try {
    const res = await fetch("/api/sounds");
    if (!res.ok) return null;
    const body = await res.json();
    const ok = body && typeof body === "object" && typeof body.enabled === "boolean"
      && (!body.enabled || (Array.isArray(body.events) && body.bind && typeof body.bind === "object"
        && body.sounds && typeof body.sounds === "object" && body.limits && typeof body.limits === "object"));
    const catalog = ok ? body : { enabled: false };
    installCatalog(catalog);
    return catalog;
  } catch {
    return null;
  }
}

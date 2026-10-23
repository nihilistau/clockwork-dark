import { installCatalog } from "./engine.js";

/** Fetch /api/sounds once per page load and install it (spec §6.1). A failure leaves the page silent, never broken. */
export async function loadCatalog() {
  try {
    const res = await fetch("/api/sounds");
    if (!res.ok) return null;
    const body = await res.json();
    installCatalog(body);
    return body;
  } catch {
    return null;
  }
}

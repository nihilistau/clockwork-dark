/**
 * Component-kit routes.
 *
 * A story whose game does not exist on the server yet still has components, and
 * components nobody has rendered are components that do not work. `?kit=<slug>`
 * mounts that story's kit page with its theme loaded and no session, no socket
 * and no server behind it.
 *
 * Deliberately NOT part of the game path: main.jsx only imports this module when
 * the query string asks for it, so a player fetches none of it. It is also not
 * a route the server knows about -- it is the same page with a query on it,
 * which means it needs nothing from the Python side to exist.
 */
import React from "react";

const KITS = {
  "wicked-garden": async () => {
    // The story's own theme, then the page scaffolding. Order matters: the
    // scaffolding reads the theme's tokens.
    await import("./stories/wicked-garden/theme/wicked-garden.css");
    await import("./stories/wicked-garden/demo/kit.css");
    const { default: Kit } = await import("./stories/wicked-garden/demo/Kit.jsx");
    return Kit;
  },
};

export default async function mountKit(root, slug) {
  const load = KITS[slug];
  if (!load) {
    root.render(
      <p style={{ padding: "2rem" }}>
        No component kit called “{slug}”. Installed: {Object.keys(KITS).join(", ")}.
      </p>
    );
    return;
  }
  const Kit = await load();
  document.title = `${slug} — component kit`;
  root.render(<Kit />);
}

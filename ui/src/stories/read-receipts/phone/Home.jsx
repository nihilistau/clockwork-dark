/**
 * The home screen (spec §18.2): every app in a grid with its unread badge,
 * and the dock -- Texts, Natter, Matchstick, Front Porch.
 */
import React from "react";

import AppIcon from "./AppIcon.jsx";
import { DOCK } from "./apps.js";

export default function Home({ phone, onOpenApp }) {
  const apps = phone.apps || [];
  const docked = DOCK.map((id) => apps.find((a) => a.id === id)).filter(Boolean);
  const grid = apps.filter((a) => !DOCK.includes(a.id));
  return (
    <div className="rr-home" data-testid="home">
      <div className="rr-home__grid">
        {grid.map((app) => (
          <AppIcon key={app.id} app={app} onOpen={onOpenApp} />
        ))}
      </div>
      <nav className="rr-dock" aria-label="Dock">
        {docked.map((app) => (
          <AppIcon key={app.id} app={app} onOpen={onOpenApp} dock />
        ))}
      </nav>
    </div>
  );
}

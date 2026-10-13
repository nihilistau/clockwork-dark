/** A person's face: their ready portrait (`avatar_url`), else a procedural tile with an initial. */
import React from "react";

import { initialOf, tileStyle } from "./format.js";

export default function Avatar({ pid, name, url, size = "md" }) {
  if (url) {
    return <img className={`rr-avatar rr-avatar--${size}`} src={url} alt="" />;
  }
  return (
    <span className={`rr-avatar rr-avatar--${size}`} style={tileStyle(pid)} aria-hidden="true">
      {initialOf(name)}
    </span>
  );
}

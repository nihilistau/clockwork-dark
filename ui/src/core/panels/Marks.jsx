/** A row of `count` marks, the first `lit` lit. Decorative: the word beside it carries the meaning. */
import React from "react";

export default function Marks({ count, lit, danger = false }) {
  const marks = [];
  for (let i = 0; i < Math.max(0, count); i += 1) {
    marks.push(<span key={i} className={`marks__mark ${i < lit ? "is-lit" : ""}`} />);
  }
  return (
    <span className={`marks ${danger ? "is-danger" : ""}`} aria-hidden="true">
      {marks}
    </span>
  );
}

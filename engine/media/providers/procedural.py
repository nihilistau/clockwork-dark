"""
Procedural Provider (always available)
======================================

Deterministic SVG stand-ins, generated instantly and offline.

This is the floor the game stands on. With no image backend configured at all,
every location and every character still has a picture -- and crucially the
picture is stable, so the same NPC looks the same on every visit.

The old client pointed at ``/static/placeholders/*.png``, a directory that has
never existed, so with ComfyUI disabled (the default) every single turn painted
a broken-image icon over the narration.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from engine.game.rng import stable_rng
from engine.media.providers.base import ImageRequest, ImageResult, IMAGE_DIR, url_for

logger = logging.getLogger(__name__)

# Palette drawn from the design tokens so procedural art sits inside the same
# world as everything else.
INK = "#080b0b"
CARD = "#1d221e"
BRASS = "#b8863f"
CANDLE = "#d6b26c"
MUTED = "#7f857c"
CORRUPT = "#8fae5a"

HEADS = ["M0,0 a26,30 0 1,0 0.1,0", "M0,0 a24,34 0 1,0 0.1,0", "M0,0 a30,28 0 1,0 0.1,0"]
GARMENTS = [
    "M-46,120 q46,-58 92,0 z",
    "M-52,120 q52,-70 104,0 z",
    "M-40,120 q40,-50 80,0 l0,0 z",
]
HEADWEAR = ["", "hood", "cap", "scarf"]


def _seed(subject_id: str) -> int:
    return int(hashlib.blake2b(subject_id.encode("utf-8"), digest_size=4).hexdigest(), 16)


def portrait_svg(subject_id: str, *, evil_phase: str = "dormant") -> str:
    """
    A deterministic woodcut silhouette for one character.

    Composed from a small parts library seeded on the id, so npc_maris is
    always the same shape -- the property that makes a fallback feel authored
    rather than random.
    """
    rng = stable_rng(_seed(subject_id), "portrait")
    head = rng.choice(HEADS)
    garment = rng.choice(GARMENTS)
    hat = rng.choice(HEADWEAR)
    reveal = {"dormant": 0.0, "stirring": 0.25, "spreading": 0.6, "consuming": 1.0}.get(
        evil_phase, 0.0
    )
    tilt = rng.uniform(-4, 4)

    hat_shape = ""
    if hat == "hood":
        hat_shape = f'<path d="M-34,-6 q34,-52 68,0 q-34,-22 -68,0 z" fill="{INK}" opacity="0.85"/>'
    elif hat == "cap":
        hat_shape = f'<path d="M-30,-18 q30,-20 60,0 l0,6 l-60,0 z" fill="{INK}" opacity="0.9"/>'
    elif hat == "scarf":
        hat_shape = f'<path d="M-30,34 q30,16 60,0 l0,10 q-30,14 -60,0 z" fill="{BRASS}" opacity="0.55"/>'

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 320" width="240" height="320" role="img" aria-label="{subject_id}">
  <defs>
    <radialGradient id="rim" cx="38%" cy="30%" r="70%">
      <stop offset="0%" stop-color="{CANDLE}" stop-opacity="0.30"/>
      <stop offset="100%" stop-color="{INK}" stop-opacity="0"/>
    </radialGradient>
    <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="3" seed="{_seed(subject_id) % 9999}"/>
      <feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope="0.10"/></feComponentTransfer></filter>
  </defs>
  <rect width="240" height="320" fill="{CARD}"/>
  <rect width="240" height="320" fill="url(#rim)"/>
  <g transform="translate(120,150) rotate({tilt:.1f})">
    <path d="{garment}" fill="{INK}" opacity="0.92"/>
    <g transform="translate(0,-40)"><path d="{head}" fill="{INK}" opacity="0.95"/>{hat_shape}</g>
  </g>
  <ellipse cx="120" cy="286" rx="62" ry="9" fill="{INK}" opacity="0.55"/>
  <rect width="240" height="320" filter="url(#grain)" opacity="0.5"/>
  <rect width="240" height="320" fill="{CORRUPT}" opacity="{reveal * 0.10:.3f}"/>
  <rect x="0.5" y="0.5" width="239" height="319" fill="none" stroke="{BRASS}" stroke-opacity="0.22"/>
</svg>"""


def location_svg(subject_id: str, *, time_of_day: str = "dawn", evil_phase: str = "dormant") -> str:
    """A layered wash for a place: horizon, treeline, mist, vignette."""
    rng = stable_rng(_seed(subject_id), "location")
    skies = {
        "dawn": ("#3a3a44", "#6b5a4a"),
        "day": ("#2f3a36", "#4a5348"),
        "dusk": ("#2a2028", "#5c3c30"),
        "night": ("#0d1118", "#1b2230"),
    }
    top, bottom = skies.get(time_of_day, skies["dawn"])
    reveal = {"dormant": 0.0, "stirring": 0.2, "spreading": 0.55, "consuming": 1.0}.get(evil_phase, 0.0)

    ridge = " ".join(
        f"{x},{190 + rng.randint(-26, 18)}" for x in range(-20, 700, 44)
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360" width="640" height="360" role="img" aria-label="{subject_id}">
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{top}"/><stop offset="100%" stop-color="{bottom}"/>
    </linearGradient>
    <filter id="soft"><feGaussianBlur stdDeviation="9"/></filter>
    <filter id="g2"><feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="3" seed="{_seed(subject_id) % 7777}"/>
      <feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope="0.09"/></feComponentTransfer></filter>
  </defs>
  <rect width="640" height="360" fill="url(#sky)"/>
  <polygon points="-20,360 {ridge} 660,360" fill="{INK}" opacity="0.72"/>
  <polygon points="-20,360 {ridge} 660,360" fill="{INK}" opacity="0.5" transform="translate(0,34)"/>
  <ellipse cx="320" cy="300" rx="330" ry="46" fill="{MUTED}" opacity="0.16" filter="url(#soft)"/>
  <rect width="640" height="360" fill="{CORRUPT}" opacity="{reveal * 0.09:.3f}"/>
  <rect width="640" height="360" filter="url(#g2)" opacity="0.55"/>
</svg>"""


class ProceduralProvider:
    """Instant, offline, deterministic image stand-ins."""

    name = "procedural"

    def available(self) -> bool:
        return True

    def generate(self, request: ImageRequest) -> ImageResult:
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        path = IMAGE_DIR / f"{request.cache_key()}.svg"

        if request.kind == "portrait":
            svg = portrait_svg(request.subject_id, evil_phase=request.evil_phase)
        else:
            svg = location_svg(
                request.subject_id,
                time_of_day=request.time_of_day,
                evil_phase=request.evil_phase,
            )

        path.write_text(svg, encoding="utf-8")
        return ImageResult(
            url=url_for(path),
            path=str(path),
            status="procedural",
            provider=self.name,
        )

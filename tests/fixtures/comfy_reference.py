"""
The v0.21.1 ComfyUI graph, kept as the test's fixed reference (v0.22.0 T17).

``engine/media/providers/comfy.py::build_workflow`` built this graph in code
until v0.22.0; the provider now binds ``config/comfyui/photo_sdxl.json``
through ``engine.media.comfy.workflows`` instead. The function below is that
``build_workflow`` copied verbatim from v0.21.1 (commit 0e5ada9), renamed
``build_workflow_v021``, so ``tests/test_comfy_client.py`` can hold the bound
template equal to it node for node while the live module is refactored
freely. Never edit its body: it is a recording, not code.
"""

from __future__ import annotations

from typing import Any

from engine.media.art import format_for, render_tags
from engine.media.providers.base import ImageRequest


def build_workflow_v021(
    request: ImageRequest,
    *,
    checkpoint: str,
    steps: int,
    cfg_scale: float,
    sampler: str,
    scheduler: str,
    seed: int,
) -> dict[str, Any]:
    """
    The ComfyUI node graph for one image.

    Args:
        request: What to draw.
        checkpoint: SDXL checkpoint filename as ComfyUI knows it.
        steps: Sampler steps.
        cfg_scale: Classifier-free guidance scale.
        sampler: KSampler sampler name.
        scheduler: KSampler scheduler name.
        seed: Sampler seed. Unlike Grok Imagine, ComfyUI HAS one, so a given
            (subject, daypart, phase) can be reproduced exactly -- which is why
            the caller derives it from the cache key rather than randomising.

    Returns:
        The ``prompt`` object for POST /prompt.
    """
    positive = render_tags(
        request.subject_id,
        kind=request.kind,
        time_of_day=request.time_of_day,
        evil_phase=request.evil_phase,
    )
    spec = format_for(request.kind)

    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive, "clip": ["1", 1]},
        },
        # KSampler requires a negative conditioning input, so the node stays;
        # it encodes an empty string because no story carries a negative
        # prompt (v0.15.1).
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "", "clip": ["1", 1]},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "width": int(spec.get("width", 1024)),
                "height": int(spec.get("height", 1024)),
                "batch_size": 1,
            },
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": int(seed),
                "steps": int(steps),
                "cfg": float(cfg_scale),
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": 1.0,
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": f"clockwork/{request.kind}_{request.subject_id}",
                "images": ["6", 0],
            },
        },
    }


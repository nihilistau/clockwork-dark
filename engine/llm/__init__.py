"""
Model-server inference: every provider row, one package.

Named after LM Studio (package ``lmstudio``) until v0.19.0, when the engine
learned to speak vLLM, the llama.cpp server, Ollama and any OpenAI-compatible
server beside it (``providers.py``; docs/MODEL_SERVERS.md). The old package
stays, beside this one, as an identity shim until v0.21.0: every old dotted
path is the same module object as its new one. ``native`` became
``lmstudio_native``, since other servers have native routes too. The ``LMS``
prefix on ``LMSClient``, ``LMSResponse`` and ``LMSStreamEvent``, and the name
``LMStudioBackend`` (also exported as ``backend.LLMBackend``), are historical;
no class was renamed.
"""

from engine.llm.client import LMSClient, get_lms_client
from engine.llm.profiles import ModelProfile, resolve_profile

__all__ = ["LMSClient", "get_lms_client", "ModelProfile", "resolve_profile"]

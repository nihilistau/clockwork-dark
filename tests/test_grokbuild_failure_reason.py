"""The Grok provider names why the CLI produced no image (v0.23.0 T27: a signed-out CLI read as "no image produced")."""

from __future__ import annotations

import json
import subprocess

from engine.media.providers.grokbuild import _explain_failure


def _done(stdout: str, stderr: str = "") -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(args=["grok"], returncode=0, stdout=stdout.encode(), stderr=stderr.encode())


def test_an_error_envelope_with_a_message_is_reported() -> None:
    envelope = {"type": "error", "message": "Not signed in. To authenticate without a browser, run: grok login"}
    assert _explain_failure(_done(json.dumps(envelope))).startswith("Not signed in")


def test_text_and_error_keys_still_win() -> None:
    assert _explain_failure(_done(json.dumps({"text": "the image tool refused"}))) == "the image tool refused"
    assert _explain_failure(_done(json.dumps({"error": "rate limited"}))) == "rate limited"


def test_an_empty_envelope_still_says_no_image() -> None:
    assert _explain_failure(_done(json.dumps({}))) == "no image produced"

"""Model selection for the demo agent. Gemini 3.x only: an older family is refused before any call is made."""
from __future__ import annotations

import os
import re
from typing import Mapping

DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_LOCATION = "global"          # Vertex AI location the recorded runs used for gemini-3.8-flash
MIN_MAJOR = 3
_GEMINI = re.compile(r"gemini-(\d+)(?:\.(\d+))?(?:-[a-z0-9.-]+)?")


class ModelRefused(ValueError):
    """The requested model id is not one this demo runs."""


def check_model(model_id: str) -> str:
    m = _GEMINI.fullmatch((model_id or "").strip())
    if not m:
        raise ModelRefused(f"{model_id!r} is not a Gemini model id this demo accepts (expected gemini-3.x, default {DEFAULT_MODEL})")
    if int(m.group(1)) < MIN_MAJOR:
        raise ModelRefused(f"{model_id!r} is older than Gemini {MIN_MAJOR}: this demo runs {DEFAULT_MODEL} or newer")
    return model_id.strip()


def resolve_model(environ: Mapping[str, str] = os.environ) -> str:
    """`DEMO_MODEL_ID`, defaulting to gemini-3.8-flash; refused when older than Gemini 3."""
    return check_model(environ.get("DEMO_MODEL_ID") or DEFAULT_MODEL)

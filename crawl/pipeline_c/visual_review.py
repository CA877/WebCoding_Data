"""Final screenshot quality gate for Pipeline C.

This gate is deliberately called only after code/resource cleanup, exact Qwen
token accounting, and a successful local-HTTP rendering check.  It judges the
frozen training answer, never the source website.

Credentials are environment-only:
``KIMI_API_KEY`` (official Moonshot) or ``VISION_OPENAI_API_KEY`` /
``VISION_OPENAI_BASE_URL`` / ``VISION_MODEL``; they fall back to the
corresponding ``OPENAI_*`` variables.  No secret is
written to manifests or source files.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from openai import OpenAI, RateLimitError


# Kimi K2.6 is usable through Moonshot's official endpoint for text, but its
# image request was not reliable in the 2026-07-16 integration test.  The
# official vision-preview endpoint is the stable multimodal Kimi/Moonshot
# model for this screenshot gate.  Set VISION_MODEL to override deliberately.
DEFAULT_MODEL = "moonshot-v1-128k-vision-preview"
PROMPT = """You are the final quality gate for a web-code training corpus.
Inspect the screenshot of a webpage rendered from its cleaned, token-limited,
local HTTP project. Return exactly one JSON object with:
{"verdict":"pass"|"reject","reasons":[short strings],"confidence":number}

PASS only a polished, complete, visually coherent, useful website/interface.
REJECT any broken/error/maintenance/closed/parked page or anti-bot challenge;
adult, unsafe, scam, spam or SEO/link-farm content; pure article/document,
directory/search/tool/admin page with no genuine user-facing value;
default/placeholder template; mostly text
with no meaningful interface; visibly missing imagery/assets; or an obsolete,
low-quality layout. Reject a page whose visible content is predominantly in a
language other than Chinese or English. Also reject a bare document-request,
download, contact, privacy, terms, link-list, or generic brochure page even if
it technically renders: a visible heading plus a few links/buttons is not a
high-quality web interface. PASS requires multiple coherent visual sections,
substantial intentional layout, and a modern usable interface. Be strict: this
is training gold, not a web archive. A curated directory or tool catalogue may
PASS when it has clear information architecture, meaningful descriptions, and
genuine user-facing functionality; reject only spammy, unrelated, parked, or
SEO-style link farms.
"""


def _env() -> tuple[str, str | None, str]:
    official_kimi_key = os.environ.get("KIMI_API_KEY")
    if official_kimi_key:
        # Do not accidentally route an official key through an inherited
        # Idealab/OpenAI base URL in the launcher environment.
        key, base_url = official_kimi_key, os.environ.get("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
    else:
        key = os.environ.get("VISION_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        base_url = os.environ.get("VISION_OPENAI_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    model = os.environ.get("VISION_MODEL") or DEFAULT_MODEL
    if not key:
        raise RuntimeError("missing_visual_api_key")
    if not base_url:
        raise RuntimeError("missing_visual_api_base_url")
    return key, base_url, model


def _json(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if not match:
        raise ValueError("visual_review_non_json")
    payload = json.loads(match.group(0))
    verdict = str(payload.get("verdict", "")).lower()
    if verdict not in {"pass", "reject"}:
        raise ValueError("visual_review_invalid_verdict")
    reasons = payload.get("reasons", [])
    if not isinstance(reasons, list):
        reasons = [str(reasons)]
    confidence = payload.get("confidence")
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = None
    return {"verdict": verdict, "reasons": [str(item)[:300] for item in reasons][:12],
            "confidence": confidence}


def _is_quota_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return isinstance(exc, RateLimitError) or any(marker in message for marker in (
        "429", "quota", "insufficient balance", "exceeded_current_quota", "suspended due to insufficient",
    ))


def review_screenshot(image: Path, *, model: str | None = None, attempts: int = 2,
                      request_timeout: float = 30.0) -> dict[str, Any]:
    """Review one screenshot with bounded retries and explicit quota outcome.

    Quota/429 is not retryable: the batch controller must open its shared
    circuit breaker immediately.  Network/parser failures retry once only.
    """
    key, base_url, configured_model = _env()
    selected_model = model or configured_model
    mime = "image/jpeg" if image.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    client = OpenAI(api_key=key, base_url=base_url, timeout=request_timeout)
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            response = client.chat.completions.create(
                model=selected_model,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                ]}],
                max_tokens=400,
                # Kimi K2.6's official endpoint currently accepts only 1.
                # The judge prompt and strict JSON parser provide stability.
                temperature=1,
            )
            parsed = _json(response.choices[0].message.content or "")
            return {"status": "pass" if parsed["verdict"] == "pass" else "reject", "model": selected_model,
                    "attempt": attempt, **parsed}
        except Exception as exc:  # API/network/parser failures are explicit and rejectable upstream.
            last_error = f"{type(exc).__name__}:{exc}"[:500]
            if _is_quota_error(exc):
                return {"status": "quota_exhausted", "model": selected_model, "attempt": attempt,
                        "reason": last_error}
            if attempt < attempts:
                time.sleep(attempt * 2)
    return {"status": "retryable", "model": selected_model, "attempt": attempts, "reason": last_error}

"""
Shared utilities for data construction pipelines.
"""

import os
import json
import base64
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI


def load_env():
    """Load .env from project root."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)


TEXT_MODEL = "qwen3-coder-plus"
VISION_MODEL = "claude_sonnet4_5"


def get_client(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> OpenAI:
    """Create an OpenAI-compatible client using env config."""
    load_env()
    base_url = base_url or os.environ.get("OPENAI_BASE_URL")
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not base_url or not api_key:
        raise ValueError("OPENAI_BASE_URL and OPENAI_API_KEY must be set in .env")
    return OpenAI(base_url=base_url, api_key=api_key)


MAX_IMAGE_BYTES = 4 * 1024 * 1024  # 4MB limit (API has 5MB, leave margin)
MAX_IMAGE_DIMENSION = 7000  # API limit is 8000px, leave margin


def _resize_image_if_needed(path: str) -> tuple[bytes, bool]:
    """Read image, resize if it exceeds size/dimension limits.

    Returns (raw_bytes, was_resized).
    """
    from PIL import Image
    import io

    with open(path, "rb") as f:
        raw = f.read()

    img = Image.open(io.BytesIO(raw))

    # Check if dimensions or size require resizing
    needs_resize = (
        len(raw) > MAX_IMAGE_BYTES
        or img.width > MAX_IMAGE_DIMENSION
        or img.height > MAX_IMAGE_DIMENSION
    )

    if not needs_resize:
        return raw, False

    # Resize dimensions first if needed
    if img.width > MAX_IMAGE_DIMENSION or img.height > MAX_IMAGE_DIMENSION:
        ratio = min(MAX_IMAGE_DIMENSION / img.width, MAX_IMAGE_DIMENSION / img.height)
        new_w = int(img.width * ratio)
        new_h = int(img.height * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    # Then compress to fit size limit
    quality = 85
    while True:
        buf = io.BytesIO()
        # Convert RGBA to RGB for JPEG
        if img.mode == "RGBA":
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()
        if len(data) <= MAX_IMAGE_BYTES:
            return data, True
        new_w = int(img.width * 0.7)
        new_h = int(img.height * 0.7)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        quality = max(60, quality - 10)


def encode_image_base64(path: str) -> str:
    """Encode an image file to base64, resizing if too large."""
    raw, _ = _resize_image_if_needed(path)
    return base64.b64encode(raw).decode("utf-8")


def call_llm_text(client: OpenAI, model: str, prompt: str) -> str:
    """Call LLM with text-only prompt."""
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content or ""


def call_llm_with_images(
    client: OpenAI,
    model: str,
    prompt: str,
    image_paths: list[str],
) -> str:
    """Call LLM with text + images. Auto-resizes large images."""
    content = [{"type": "text", "text": prompt}]
    for p in image_paths:
        raw, was_resized = _resize_image_if_needed(p)
        # If we resized, it's JPEG now; otherwise keep original format
        if was_resized:
            mime = "image/jpeg"
        else:
            ext = Path(p).suffix.lower().lstrip(".")
            mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}
            mime = mime_map.get(ext, "image/png")
        b64 = base64.b64encode(raw).decode("utf-8")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"}
        })
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
    )
    return resp.choices[0].message.content or ""


def append_jsonl(path: str, obj: dict):
    """Append one JSON object to a JSONL file."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_file(path: str) -> str:
    """Read a text file, return its content."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

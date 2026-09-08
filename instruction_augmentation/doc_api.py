"""Retry-free Doc API client with persistent request and usage evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from openai import OpenAI

from instruction_augmentation.production import parse_json_object


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_CHAT_MODEL = "qwen3.8-max"
DEFAULT_EMBEDDING_MODEL = "text-embedding-v4"


def chat_extra_body(base_url: str) -> dict[str, Any]:
    if urlsplit(base_url).hostname == "api.deepseek.com":
        return {"thinking": {"type": "disabled"}}
    return {"enable_thinking": False}


def build_chat_messages(
    *,
    system_prompt: str,
    stable_context: str,
    task: str,
    cache_stable_context: bool,
    images: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    stable_part: dict[str, Any] = {"type": "text", "text": stable_context}
    if cache_stable_context:
        stable_part["cache_control"] = {"type": "ephemeral"}
    content = [stable_part, {"type": "text", "text": task}]
    for item in images or []:
        content.extend([{"type":"text", "text":f"Screenshot state_id: {item['state_id']}"},
                        {"type":"image_url", "image_url":{"url":item['url']}}])
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": content,
        },
    ]


def usage_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    return dict(value) if isinstance(value, dict) else {}


def usage_cache_counts(value: Any) -> dict[str, int]:
    usage = usage_dict(value)
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    if not isinstance(details, dict):
        details = {}
    return {
        "cached_tokens": int(
            usage.get("cached_tokens")
            or usage.get("cache_read_input_tokens")
            or details.get("cached_tokens")
            or details.get("cache_read_input_tokens")
            or 0
        ),
        "cache_creation_input_tokens": int(
            usage.get("cache_creation_input_tokens")
            or details.get("cache_creation_input_tokens")
            or 0
        ),
    }


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


class DocApiClient:
    """One-request-at-a-time client. The SDK and outer workflow never retry."""

    def __init__(
        self,
        *,
        api_key: str,
        log_dir: Path,
        base_url: str | None = None,
        chat_model: str | None = None,
        embedding_model: str | None = None,
        timeout_seconds: float = 1200.0,
    ) -> None:
        if not api_key:
            raise ValueError("Doc API key is required")
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = (
            base_url or os.environ.get("DOC_API_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.chat_model = (
            chat_model or os.environ.get("DOC_API_CHAT_MODEL") or DEFAULT_CHAT_MODEL
        )
        self.embedding_model = (
            embedding_model
            or os.environ.get("DOC_API_EMBEDDING_MODEL")
            or DEFAULT_EMBEDDING_MODEL
        )
        self._is_deepseek = urlsplit(self.base_url).hostname == "api.deepseek.com"
        self.http_client = httpx.Client(trust_env=False, verify=True, timeout=timeout_seconds)
        self.client = OpenAI(
            api_key=api_key,
            base_url=self.base_url,
            timeout=timeout_seconds,
            max_retries=0,
            http_client=self.http_client,
        )

    def close(self) -> None:
        self.http_client.close()

    def __enter__(self) -> "DocApiClient":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def _write_request(self, request_id: str, payload: dict[str, Any]) -> None:
        path = self.log_dir / "requests" / f"{request_id}.json"
        if path.exists():
            raise FileExistsError(f"request id already exists: {request_id}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _record(
        self,
        *,
        request_id: str,
        kind: str,
        model: str,
        status: str,
        usage: Any,
        stream: bool | None,
        error: str | None = None,
    ) -> None:
        usage_payload = usage_dict(usage)
        _append_jsonl(
            self.log_dir / "usage.jsonl",
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "request_id": request_id,
                "kind": kind,
                "model": model,
                "stream": stream,
                "status": status,
                "sdk_retries": 0,
                "outer_retries": 0,
                "usage": usage_payload,
                **usage_cache_counts(usage_payload),
                "error": error,
            },
        )

    def chat_text(
        self,
        *,
        request_id: str,
        system_prompt: str,
        stable_context: str,
        task: str,
        max_tokens: int,
        stream: bool,
        temperature: float = 0.0,
        cache_stable_context: bool = True,
        images: list[dict[str, str]] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        if not system_prompt.strip() or not stable_context.strip() or not task.strip():
            raise ValueError("chat prompts must be non-empty")
        if urlsplit(self.base_url).hostname == 'api.tokenwave.us':
            content = [{'type':'input_text','text':stable_context + '\n\n' + task}]
            for item in images or []:
                content.extend([{'type':'input_text','text':f"Screenshot state_id: {item['state_id']}"},
                                {'type':'input_image','image_url':item['url']}])
            payload = dict(model=self.chat_model, instructions=system_prompt,
                input=[{'role':'user','content':content}], max_output_tokens=max_tokens,
                store=False, stream=stream)
            self._write_request(request_id, payload)
            usage = None
            try:
                response = self.client.responses.create(**payload)
                if stream:
                    event_stream = response
                    response = None
                    try:
                        for event in event_stream:
                            if event.type in {'response.completed', 'response.incomplete', 'response.failed'}:
                                response = event.response
                            elif event.type == 'error':
                                raise ValueError('TokenWave streaming API error')
                    finally:
                        event_stream.close()
                    if response is None:
                        raise ValueError('TokenWave stream ended without a terminal response')
                usage = response.usage
                if response.status != 'completed' or not response.output_text.strip():
                    raise ValueError('TokenWave response incomplete or empty')
                text = response.output_text
                path = self.log_dir / 'responses' / f'{request_id}.txt'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding='utf-8')
                self._record(request_id=request_id,kind='chat',model=self.chat_model,
                    status='ok',usage=usage,stream=stream)
                return text, usage_dict(usage)
            except Exception as exc:
                self._record(request_id=request_id,kind='chat',model=self.chat_model,
                    status='error',usage=usage,stream=stream,error=f'{type(exc).__name__}: {exc}')
                raise
        messages = build_chat_messages(
            system_prompt=system_prompt,
            stable_context=stable_context,
            task=task,
            cache_stable_context=cache_stable_context and not self._is_deepseek,
            images=images,
        )
        extra_body = chat_extra_body(self.base_url)
        request_payload = {
            "model": self.chat_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
            "extra_body": extra_body,
        }
        self._write_request(request_id, request_payload)
        usage: Any = None
        try:
            if stream:
                response = self.client.chat.completions.create(
                    model=self.chat_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                    stream_options={"include_usage": True},
                    extra_body=extra_body,
                )
                chunks: list[str] = []
                for chunk in response:
                    if getattr(chunk, "usage", None) is not None:
                        usage = chunk.usage
                    if chunk.choices and chunk.choices[0].delta.content:
                        chunks.append(chunk.choices[0].delta.content)
                text = "".join(chunks)
            else:
                response = self.client.chat.completions.create(
                    model=self.chat_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=False,
                    extra_body=extra_body,
                )
                usage = response.usage
                text = response.choices[0].message.content or ""
            response_path = self.log_dir / "responses" / f"{request_id}.txt"
            response_path.parent.mkdir(parents=True, exist_ok=True)
            response_path.write_text(text, encoding="utf-8")
            self._record(
                request_id=request_id,
                kind="chat",
                model=self.chat_model,
                status="ok",
                usage=usage,
                stream=stream,
            )
            return text, usage_dict(usage)
        except Exception as exc:
            self._record(
                request_id=request_id,
                kind="chat",
                model=self.chat_model,
                status="error",
                usage=usage,
                stream=stream,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

    def chat_json(self, **kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        text, usage = self.chat_text(**kwargs)
        return parse_json_object(text), usage

    def embeddings(
        self,
        *,
        request_id: str,
        inputs: list[str],
        dimensions: int = 1024,
    ) -> tuple[list[list[float]], dict[str, Any]]:
        if not isinstance(inputs, list) or not inputs or len(inputs) > 10:
            raise ValueError("embedding input requires 1 to 10 texts")
        if not all(isinstance(item, str) and item.strip() for item in inputs):
            raise ValueError("embedding inputs must be non-empty strings")
        payload = {
            "model": self.embedding_model,
            "input": inputs,
            "dimensions": dimensions,
        }
        self._write_request(request_id, payload)
        usage: Any = None
        try:
            response = self.client.embeddings.create(
                model=self.embedding_model,
                input=inputs,
                dimensions=dimensions,
            )
            usage = response.usage
            vectors = [list(item.embedding) for item in response.data]
            response_path = self.log_dir / "responses" / f"{request_id}.json"
            response_path.parent.mkdir(parents=True, exist_ok=True)
            response_path.write_text(
                json.dumps(
                    {
                        "model": self.embedding_model,
                        "dimensions": dimensions,
                        "vector_count": len(vectors),
                        "vectors": vectors,
                        "usage": usage_dict(usage),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            self._record(
                request_id=request_id,
                kind="embedding",
                model=self.embedding_model,
                status="ok",
                usage=usage,
                stream=None,
            )
            return vectors, usage_dict(usage)
        except Exception as exc:
            self._record(
                request_id=request_id,
                kind="embedding",
                model=self.embedding_model,
                status="error",
                usage=usage,
                stream=None,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_CHAT_MODEL",
    "DEFAULT_EMBEDDING_MODEL",
    "DocApiClient",
    "build_chat_messages",
    "usage_cache_counts",
    "usage_dict",
]

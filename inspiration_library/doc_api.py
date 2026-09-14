"""Retry-free Doc API client with persistent request and usage evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import openai
from openai import OpenAI

from inspiration_library.production import parse_json_object


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_CHAT_MODEL = "qwen3.8-max"
DEFAULT_EMBEDDING_MODEL = "text-embedding-v4"


class ProviderResponseError(ValueError):
    def __init__(self, reason: str, *, retryable: bool = True, code: str | None = None):
        super().__init__(reason)
        self.retryable = retryable
        self.fatal = code in {'insufficient_quota', 'billing_hard_limit_reached', 'invalid_api_key',
                              'authentication_error', 'access_terminated_error'}


def retryable_request_error(exc):
    if isinstance(exc, ProviderResponseError):
        return exc.retryable and not exc.fatal
    if isinstance(exc, openai.APIStatusError):
        if getattr(exc, 'code', None) in {'insufficient_quota', 'billing_hard_limit_reached'}:
            return False
        return exc.status_code in {408, 409, 429} or exc.status_code >= 500
    return isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError, httpx.TransportError))


def checked_response_text(response):
    status = getattr(response, 'status', None)
    details = getattr(response, 'incomplete_details', None)
    reason = getattr(details, 'reason', None)
    if status == 'incomplete':
        # Repeating the same output limit/content filter cannot repair this sample.
        raise ProviderResponseError(f'response_incomplete:{reason or "unknown"}',
                                    retryable=reason not in {'max_output_tokens', 'content_filter'})
    error = getattr(response, 'error', None)
    code = getattr(error, 'code', None)
    if status == 'failed':
        raise ProviderResponseError(f'response_failed:{code or "unknown"}',
                                    retryable=code not in {'invalid_prompt', 'content_filter'}, code=code)
    text = getattr(response, 'output_text', '') or ''
    if status != 'completed' or not text.strip():
        raise ProviderResponseError('response_empty_or_unfinished')
    return text


def chat_extra_body(base_url: str) -> dict[str, Any]:
    parsed = urlsplit(base_url)
    if parsed.hostname == "open.bigmodel.cn" and "/api/coding/" in parsed.path:
        return {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}
    if parsed.hostname == "api.deepseek.com":
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
        content.extend([{"type":"text", "text":f"Screenshot state_id: {', '.join(item.get('state_ids', [item['state_id']]))}"},
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
    """Zero SDK retries; optional bounded recovery of only the failed chat request."""

    def __init__(
        self,
        *,
        api_key: str,
        log_dir: Path,
        base_url: str | None = None,
        chat_model: str | None = None,
        embedding_model: str | None = None,
        timeout_seconds: float = 1200.0,
        request_attempts: int = 1,
    ) -> None:
        if not api_key:
            raise ValueError("Doc API key is required")
        if request_attempts not in (1, 2, 3):
            raise ValueError('request_attempts must be 1-3')
        self.request_attempts = request_attempts
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = (
            base_url or os.environ.get("DOC_API_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.chat_model = (
            chat_model or os.environ.get("DOC_API_CHAT_MODEL") or DEFAULT_CHAT_MODEL
        )
        parsed_base = urlsplit(self.base_url)
        self._is_glm_coding = (
            parsed_base.hostname == "open.bigmodel.cn"
            and "/api/coding/" in parsed_base.path
        )
        self.embedding_model = (
            embedding_model
            or os.environ.get("DOC_API_EMBEDDING_MODEL")
            or DEFAULT_EMBEDDING_MODEL
        )
        self._is_deepseek = urlsplit(self.base_url).hostname == "api.deepseek.com"
        api_proxy = os.environ.get("DOC_API_PROXY") or (
            os.environ.get("TOKENWAVE_API_PROXY") if urlsplit(self.base_url).hostname == "api.tokenwave.us" else None)
        self.http_client = httpx.Client(trust_env=False, verify=True, timeout=timeout_seconds, proxy=api_proxy)
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
        outer_retries: int = 0,
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
                "outer_retries": outer_retries,
                "usage": usage_payload,
                **usage_cache_counts(usage_payload),
                "error": error,
            },
        )

    def chat_text(self, *, request_id: str, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        for index in range(self.request_attempts):
            attempt_id = request_id if index == 0 else f'{request_id}__retry_{index+1}'
            try:
                text, usage = self._chat_text_once(request_id=attempt_id, _retry_index=index, **kwargs)
                if index:
                    # Callers can reuse the successful logical response without replaying earlier stages.
                    target = self.log_dir/'responses'/f'{request_id}.txt'
                    with target.open('x', encoding='utf-8') as output:
                        output.write(text)
                return text, usage
            except Exception as exc:
                if index+1 >= self.request_attempts or not retryable_request_error(exc):
                    raise
                delay = 5 * 2**index
                _append_jsonl(self.log_dir/'request_retries.jsonl', dict(
                    request_id=request_id, failed_attempt=attempt_id, next_attempt=index+2,
                    delay_seconds=delay, error_type=type(exc).__name__))
                time.sleep(delay)
        raise AssertionError('unreachable request attempt loop')

    def _chat_text_once(
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
        json_output: bool = False,
        _retry_index: int = 0,
    ) -> tuple[str, dict[str, Any]]:
        if not system_prompt.strip() or not stable_context.strip() or not task.strip():
            raise ValueError("chat prompts must be non-empty")
        if urlsplit(self.base_url).hostname == "api.kimi.com":
            temperature = 1.0
        if urlsplit(self.base_url).hostname == 'api.tokenwave.us':
            content = [{'type':'input_text','text':stable_context + '\n\n' + task}]
            for item in images or []:
                content.extend([{'type':'input_text','text':f"Screenshot state_id: {', '.join(item.get('state_ids', [item['state_id']]))}"},
                                {'type':'input_image','image_url':item['url']}])
            payload = dict(model=self.chat_model, instructions=system_prompt,
                input=[{'role':'user','content':content}], max_output_tokens=max_tokens,
                store=False, stream=stream)
            if json_output:
                payload["text"] = {"format": {"type": "json_object"}}
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
                                code = getattr(event, 'code', None)
                                raise ProviderResponseError(f'stream_error:{code or "unknown"}', code=code)
                    finally:
                        event_stream.close()
                    if response is None:
                        raise ProviderResponseError('stream_missing_terminal_response')
                usage = response.usage
                text = checked_response_text(response)
                path = self.log_dir / 'responses' / f'{request_id}.txt'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding='utf-8')
                self._record(request_id=request_id,kind='chat',model=self.chat_model,
                    status='ok',usage=usage,stream=stream,outer_retries=_retry_index)
                return text, usage_dict(usage)
            except Exception as exc:
                self._record(request_id=request_id,kind='chat',model=self.chat_model,
                    status='error',usage=usage,stream=stream,error=f'{type(exc).__name__}: {exc}',outer_retries=_retry_index)
                raise
        messages = build_chat_messages(
            system_prompt=system_prompt,
            stable_context=stable_context,
            task=task,
            cache_stable_context=cache_stable_context and not self._is_deepseek and not self._is_glm_coding,
            images=None if self._is_glm_coding else images,
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
                outer_retries=_retry_index,
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
                outer_retries=_retry_index,
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

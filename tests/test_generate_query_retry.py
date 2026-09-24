import json

import pytest

import reverse.generate.query.generate as query_generate


class FakeResponse:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        return iter(self.events)


def sse(event):
    return ("data: " + json.dumps(event) + "\n").encode()


def test_vision_query_plain_stream_requires_and_strips_end_marker(monkeypatch):
    response = FakeResponse([
        sse({"type": "response.output_text.delta", "delta": "Build a detailed app.<<<END_QUERY>>>"}),
        sse({"type": "response.completed", "response": {"usage": {"total_tokens": 10}}}),
    ])
    monkeypatch.setattr(query_generate, "urlopen", lambda *_args, **_kwargs: response)

    result, usage = query_generate.call_llm(
        "https://example.test/v1", "secret", "model", "prompt", 10,
        "responses", "actor", None, plain_query=True,
    )

    assert result == {"query": "Build a detailed app."}
    assert usage == {"total_tokens": 10}


def test_vision_query_rejects_incomplete_plain_stream(monkeypatch):
    response = FakeResponse([
        sse({"type": "response.output_text.delta", "delta": "partial query"}),
        sse({"type": "response.incomplete", "response": {"status": "incomplete"}}),
    ])
    monkeypatch.setattr(query_generate, "urlopen", lambda *_args, **_kwargs: response)

    with pytest.raises(RuntimeError, match="incomplete query stream"):
        query_generate.call_llm(
            "https://example.test/v1", "secret", "model", "prompt", 10,
            "responses", "actor", None, plain_query=True,
        )

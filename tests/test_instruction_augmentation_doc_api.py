from __future__ import annotations

import unittest
from types import SimpleNamespace
import pytest

from instruction_augmentation.doc_api import (
    build_chat_messages,
    chat_extra_body,
    usage_cache_counts,
    usage_dict,
    DocApiClient,
)


def test_tokenwave_uses_responses_without_dashscope_parameters(tmp_path, monkeypatch):
    captured=[]
    with DocApiClient(api_key='unit-test-only',log_dir=tmp_path,
                      base_url='https://api.tokenwave.us/v1',chat_model='configured-model') as api:
        def respond(**kw):
            captured.append(kw)
            return SimpleNamespace(status='completed',output_text='{"ok":true}',usage={'total_tokens':3})
        monkeypatch.setattr(api.client.responses,'create',respond)
        result,_=api.chat_json(request_id='unit',system_prompt='Rules',stable_context='Evidence',
                              task='Task',max_tokens=100,stream=False)
    assert result=={'ok':True}
    assert captured[0]['store'] is False
    assert captured[0]['model']=='configured-model'
    assert 'extra_body' not in captured[0]
    assert 'cache_control' not in str(captured[0])


def test_tokenwave_incomplete_response_is_not_success(tmp_path,monkeypatch):
    with DocApiClient(api_key='unit-test-only',log_dir=tmp_path,
                      base_url='https://api.tokenwave.us/v1',chat_model='configured-model') as api:
        monkeypatch.setattr(api.client.responses,'create',lambda **kw:
            SimpleNamespace(status='incomplete',output_text='partial',usage={}))
        with pytest.raises(ValueError,match='incomplete'):
            api.chat_text(request_id='unit',system_prompt='Rules',stable_context='Evidence',
                          task='Task',max_tokens=100,stream=False)
    assert not (tmp_path/'responses/unit.txt').exists()


@pytest.mark.parametrize('terminal', ['completed', 'incomplete', None])
def test_tokenwave_stream_requires_completed_event_and_closes(tmp_path, monkeypatch, terminal):
    class Events:
        closed = False
        def __iter__(self):
            yield SimpleNamespace(type='response.output_text.delta', delta='partial')
            if terminal:
                yield SimpleNamespace(type='response.'+terminal, response=SimpleNamespace(
                    status=terminal, output_text='{"ok":true}', usage={'total_tokens':3}))
        def close(self):
            self.closed = True
    events = Events()
    with DocApiClient(api_key='unit-test-only', log_dir=tmp_path,
                      base_url='https://api.tokenwave.us/v1', chat_model='configured-model') as api:
        def respond(**kwargs):
            assert kwargs['stream'] is True
            return events
        monkeypatch.setattr(api.client.responses, 'create', respond)
        kwargs = dict(request_id='stream', system_prompt='Rules', stable_context='Evidence',
                      task='Task', max_tokens=100, stream=True)
        if terminal == 'completed':
            assert api.chat_json(**kwargs)[0] == {'ok':True}
        else:
            with pytest.raises(ValueError):
                api.chat_json(**kwargs)
            assert not (tmp_path/'responses/stream.txt').exists()
    assert events.closed


class UsageObject:
    def model_dump(self):
        return {
            "prompt_tokens": 100,
            "prompt_tokens_details": {
                "cached_tokens": 80,
                "cache_creation_input_tokens": 20,
            },
        }


class DocApiHelpersTest(unittest.TestCase):
    def test_labelled_images_are_sent_after_text(self):
        messages = build_chat_messages(system_prompt="system", stable_context="rules", task="facts",
            cache_stable_context=False, images=[{"state_id":"sort__step_1","url":"data:image/png;base64,AA=="}])
        content = messages[1]["content"]
        self.assertEqual(content[-2]["text"], "Screenshot state_id: sort__step_1")
        self.assertEqual(content[-1]["type"], "image_url")

    def test_provider_specific_non_thinking_parameter(self) -> None:
        self.assertEqual(
            chat_extra_body("https://api.deepseek.com"),
            {"thinking": {"type": "disabled"}},
        )
        self.assertEqual(
            chat_extra_body("https://dashscope.aliyuncs.com/compatible-mode/v1"),
            {"enable_thinking": False},
        )

    def test_one_shot_prompt_can_disable_explicit_cache_creation(self) -> None:
        messages = build_chat_messages(
            system_prompt="system",
            stable_context="host-specific Top-K evidence",
            task="produce Q1-Q5",
            cache_stable_context=False,
        )

        self.assertNotIn("cache_control", messages[1]["content"][0])

        cached = build_chat_messages(
            system_prompt="system",
            stable_context="shared rubric",
            task="case-specific task",
            cache_stable_context=True,
        )
        self.assertEqual(
            cached[1]["content"][0]["cache_control"], {"type": "ephemeral"}
        )

    def test_usage_parsing_reads_nested_cache_fields(self) -> None:
        payload = usage_dict(UsageObject())
        counts = usage_cache_counts(payload)

        self.assertEqual(counts["cached_tokens"], 80)
        self.assertEqual(counts["cache_creation_input_tokens"], 20)

    def test_usage_parsing_accepts_provider_top_level_fields(self) -> None:
        counts = usage_cache_counts(
            {"cache_read_input_tokens": 12, "cache_creation_input_tokens": 6}
        )

        self.assertEqual(counts, {"cached_tokens": 12, "cache_creation_input_tokens": 6})


if __name__ == "__main__":
    unittest.main()

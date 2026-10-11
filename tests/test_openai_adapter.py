import sys
import types

import pytest

from gcsi.llm.openai_compat import OpenAICompatClient


def fake_openai(captured, fail_json_mode=False):
    class Msg:
        content = '{"ok": true}'

    class Choice:
        message = Msg()

    class Usage:
        prompt_tokens, completion_tokens = 10, 5

    class Resp:
        choices = [Choice()]
        usage = Usage()
        model = "gpt-test"

    class Completions:
        def create(self, **kw):
            if fail_json_mode and "response_format" in kw:
                raise ValueError("response_format is not supported")
            captured.append(kw)
            return Resp()

    class Chat:
        completions = Completions()

    class OpenAI:
        def __init__(self, api_key=None, base_url=None, timeout=None):
            captured.append({"api_key": api_key, "base_url": base_url})
            self.chat = Chat()

    m = types.ModuleType("openai")
    m.OpenAI = OpenAI
    return m


def test_requires_a_key(monkeypatch):
    monkeypatch.delenv("GCSI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "openai", fake_openai([]))
    with pytest.raises(ValueError):
        OpenAICompatClient()


def test_request_shape_and_env_key(monkeypatch):
    cap = []
    monkeypatch.setitem(sys.modules, "openai", fake_openai(cap))
    monkeypatch.setenv("GCSI_API_KEY", "k-test")
    c = OpenAICompatClient(model="m1", base_url="http://localhost:1/v1")
    r = c.complete("sys", "usr", temperature=0.2, seed=7, repeat=2)
    assert cap[0] == {"api_key": "k-test", "base_url": "http://localhost:1/v1"}
    kw = cap[1]
    assert kw["model"] == "m1" and kw["temperature"] == 0.2 and kw["seed"] == 9
    assert kw["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in kw["messages"]] == ["system", "user"]
    assert r.text == '{"ok": true}' and r.prompt_tokens == 10 and r.error is None


def test_falls_back_when_endpoint_lacks_json_mode(monkeypatch):
    cap = []
    monkeypatch.setitem(sys.modules, "openai", fake_openai(cap, fail_json_mode=True))
    c = OpenAICompatClient(api_key="k")
    r = c.complete("s", "u")
    assert "response_format" not in cap[-1] and r.text


def test_key_is_not_in_cache_records(monkeypatch, tmp_path):
    from gcsi.llm import CachedLLM

    monkeypatch.setitem(sys.modules, "openai", fake_openai([]))
    c = CachedLLM(OpenAICompatClient(api_key="SECRET-KEY-123"), path=str(tmp_path / "c.jsonl"))
    c.complete("s", "u")
    assert "SECRET-KEY-123" not in (tmp_path / "c.jsonl").read_text()

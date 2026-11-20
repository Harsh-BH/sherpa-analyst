import dataclasses
import json
import subprocess
from types import SimpleNamespace

import pytest

from sherpa import llm
from sherpa.config import settings

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False}


def use(monkeypatch, **kw):
    s = dataclasses.replace(settings(), **kw)
    monkeypatch.setattr(llm, "settings", lambda: s)


def fake_run(stdout, returncode=0, stderr=""):
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)
    return run, calls


def test_backend_auto(monkeypatch):
    use(monkeypatch, llm_backend="auto", anthropic_api_key="sk-x")
    assert llm.backend() == "anthropic"
    use(monkeypatch, llm_backend="auto", anthropic_api_key="")
    monkeypatch.setattr(llm.shutil, "which", lambda _: "/usr/bin/claude")
    assert llm.backend() == "claude-cli"
    monkeypatch.setattr(llm.shutil, "which", lambda _: None)
    assert llm.backend() == "none"
    use(monkeypatch, llm_backend="claude-cli", anthropic_api_key="sk-x")
    assert llm.backend() == "claude-cli"


def test_none_raises(monkeypatch):
    use(monkeypatch, llm_backend="none")
    with pytest.raises(llm.LLMUnavailable):
        llm.structured(system="s", user="u", schema=SCHEMA, model="m")


def test_cli_structured_output(monkeypatch):
    use(monkeypatch, llm_backend="claude-cli")
    out = {"is_error": False, "structured_output": {"a": "x"}, "total_cost_usd": 0.01,
           "usage": {"input_tokens": 5, "cache_read_input_tokens": 100, "output_tokens": 7}}
    run, calls = fake_run(json.dumps(out))
    monkeypatch.setattr(llm.subprocess, "run", run)
    data, usage = llm.structured(system="SYS", user="USER", schema=SCHEMA, model="claude-haiku-5-5")
    assert data == {"a": "x"}
    assert usage["backend"] == "claude-cli" and usage["cost_usd"] == 0.01
    assert usage["input_tokens"] == 105 and usage["output_tokens"] == 7 and "latency_ms" in usage
    cmd, kw = calls[0]
    assert cmd[:2] == ["claude", "-p"] and kw["input"] == "USER" and kw["timeout"] == 180
    assert cmd[cmd.index("--system-prompt") + 1] == "SYS"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == SCHEMA
    assert cmd[cmd.index("--tools") + 1] == ""


def test_cli_text_fallback(monkeypatch):
    use(monkeypatch, llm_backend="claude-cli")
    out = {"is_error": False, "result": "Here you go:\n```json\n{\"a\": \"y\"}\n```", "usage": {}}
    monkeypatch.setattr(llm.subprocess, "run", fake_run(json.dumps(out))[0])
    assert llm.structured(system="s", user="u", schema=SCHEMA, model="m")[0] == {"a": "y"}


@pytest.mark.parametrize("stdout,rc", [
    ("not json at all", 1),                                                  # crash
    (json.dumps({"is_error": True, "result": "Credit balance too low"}), 1), # CLI-reported error
    (json.dumps({"is_error": False, "result": "I cannot help"}), 0),         # prose, no JSON
    (json.dumps({"is_error": False, "structured_output": {"b": 1}}), 0),     # missing required key
    (json.dumps({"is_error": False, "structured_output": [1, 2]}), 0),       # not an object
])
def test_cli_failures(monkeypatch, stdout, rc):
    use(monkeypatch, llm_backend="claude-cli")
    monkeypatch.setattr(llm.subprocess, "run", fake_run(stdout, rc, stderr="boom")[0])
    with pytest.raises(llm.LLMUnavailable):
        llm.structured(system="s", user="u", schema=SCHEMA, model="m")


def test_cli_timeout(monkeypatch):
    use(monkeypatch, llm_backend="claude-cli")

    def run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])
    monkeypatch.setattr(llm.subprocess, "run", run)
    with pytest.raises(llm.LLMUnavailable, match="timed out"):
        llm.structured(system="s", user="u", schema=SCHEMA, model="m")


def test_anthropic_request_shape(monkeypatch):
    import anthropic
    use(monkeypatch, llm_backend="anthropic", anthropic_api_key="sk-test")
    seen = {}

    class FakeMessages:
        def create(self, **kw):
            seen.update(kw)
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text='{"a": "z"}')],
                usage=SimpleNamespace(input_tokens=1000, output_tokens=100, cache_read_input_tokens=9000,
                                      cache_creation_input_tokens=0))

    class FakeClient:
        def __init__(self, **kw):
            self.beta = SimpleNamespace(messages=FakeMessages())
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    data, usage = llm.structured(system="SYS", user="U", schema=SCHEMA, model="claude-opus-5-5")
    assert data == {"a": "z"}
    assert seen["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert seen["output_config"]["format"]["type"] == "json_schema"
    assert seen["thinking"] == {"type": "adaptive"} and seen["fallbacks"] == "default"
    # 1000*4 + 9000*0.4 + 100*20 per 1M
    assert usage["cost_usd"] == pytest.approx((4000 + 3600 + 2000) / 1e6)
    assert usage["input_tokens"] == 10000


def test_anthropic_refusal(monkeypatch):
    import anthropic
    use(monkeypatch, llm_backend="anthropic", anthropic_api_key="sk-test")

    class FakeClient:
        def __init__(self, **kw):
            self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **k: SimpleNamespace(
                stop_reason="refusal", content=[], usage=None)))
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    with pytest.raises(llm.LLMUnavailable, match="refusal"):
        llm.structured(system="s", user="u", schema=SCHEMA, model="claude-haiku-5-5")

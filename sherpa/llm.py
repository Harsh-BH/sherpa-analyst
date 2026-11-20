"""One structured-output call to Claude, through the Anthropic SDK or the `claude -p` CLI.

backend() resolves settings().llm_backend; structured() returns (json_dict, usage) or raises LLMUnavailable.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time

from .config import settings

TIMEOUT_S = 180
EFFORT = "medium"   # planning and narration are translation tasks; Opus 5.5 also defaults to medium
# Server-side refusal fallback (beta) exists for these models only; Haiku has none.
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5", "claude-fable-5-2", "claude-fable-5-1"}
# USD per 1M tokens (input, output); cache reads bill 0.1x input, cache writes 1.25x.
# ponytail: hardcoded list prices, read them from the Models/Usage API if the bill must be exact
_PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}


class LLMUnavailable(Exception):
    """No backend configured, or the call failed / returned something unusable."""


def backend() -> str:
    b = settings().llm_backend
    if b != "auto":
        return b
    if settings().anthropic_api_key:
        return "anthropic"
    return "claude-cli" if shutil.which("claude") else "none"


def structured(*, system: str, user: str, schema: dict, model: str, max_tokens: int = 4096) -> tuple[dict, dict]:
    b = backend()
    t0 = time.monotonic()
    if b == "anthropic":
        data, usage = _anthropic(system, user, schema, model, max_tokens)
    elif b == "claude-cli":
        data, usage = _cli(system, user, schema, model)
    else:
        raise LLMUnavailable(f"no LLM backend ({settings().llm_backend!r} resolved to {b!r})")
    _check_required(data, schema)
    usage.update(backend=b, model=model, latency_ms=int((time.monotonic() - t0) * 1000))
    return data, usage


def strict_schema(node):
    """Pydantic JSON schema -> structured-output schema both backends accept: no titles/defaults,
    closed objects, every key required (optional fields stay nullable)."""
    if isinstance(node, list):
        return [strict_schema(x) for x in node]
    if not isinstance(node, dict):
        return node
    out = {k: strict_schema(v) for k, v in node.items() if k not in ("title", "default")}
    if out.get("type") == "object" and "properties" in out:
        out["additionalProperties"] = False
        out["required"] = list(out["properties"])
    return out


def _check_required(data: object, schema: dict) -> None:
    if not isinstance(data, dict):
        raise LLMUnavailable(f"model returned {type(data).__name__}, expected a JSON object")
    missing = [k for k in schema.get("required", []) if k not in data]
    if missing:
        raise LLMUnavailable(f"model output is missing required keys: {missing}")


def _anthropic(system: str, user: str, schema: dict, model: str, max_tokens: int) -> tuple[dict, dict]:
    import anthropic

    client = anthropic.Anthropic(api_key=settings().anthropic_api_key, timeout=TIMEOUT_S)
    extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if model in _FALLBACK_MODELS else {}
    try:
        resp = client.beta.messages.create(
            model=model,
            max_tokens=max_tokens,
            # stable system prompt first and cached; the per-question user message comes after the breakpoint
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT,
                           "format": {"type": "json_schema", "schema": anthropic.transform_schema(schema)}},
            **extra,
        )
    except anthropic.APIStatusError as e:
        raise LLMUnavailable(f"Anthropic API {e.status_code}: {e.message}"[:500]) from e
    except anthropic.APIError as e:   # connection errors and timeouts
        raise LLMUnavailable(f"Anthropic API: {e}"[:500]) from e
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise LLMUnavailable(f"model stopped with {resp.stop_reason}")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    u = resp.usage
    cr, cw = u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0
    pin, pout = _PRICES.get(model, (0.0, 0.0))
    cost = (u.input_tokens * pin + cr * pin * 0.1 + cw * pin * 1.25 + u.output_tokens * pout) / 1e6
    usage = {"input_tokens": u.input_tokens + cr + cw, "output_tokens": u.output_tokens,
             "cache_read_input_tokens": cr, "cost_usd": round(cost, 6)}
    return _loads(text), usage


def _cli(system: str, user: str, schema: dict, model: str) -> tuple[dict, dict]:
    # Strip Claude Code down to a plain completion: own system prompt, no tools, MCP, settings (hooks),
    # skills or session files, run from a neutral cwd so no project CLAUDE.md is picked up.
    # --bare would also do it but only authenticates with an API key, not the user's Claude login.
    cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--json-schema", json.dumps(schema),
           "--system-prompt", system, "--tools", "", "--no-session-persistence", "--strict-mcp-config",
           "--setting-sources", "", "--disable-slash-commands", "--effort", EFFORT]
    env = {k: v for k, v in os.environ.items() if not (k == "ANTHROPIC_API_KEY" and not v)}
    try:
        p = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=TIMEOUT_S,
                           cwd=tempfile.gettempdir(), env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise LLMUnavailable(f"claude CLI: {e}"[:500]) from e
    try:
        out = json.loads(p.stdout)
    except json.JSONDecodeError:
        raise LLMUnavailable(f"claude CLI exit {p.returncode}: {(p.stderr or p.stdout).strip()[-500:]}") from None
    if p.returncode != 0 or out.get("is_error"):
        raise LLMUnavailable(f"claude CLI error: {str(out.get('result') or p.stderr).strip()[-500:]}")
    data = out.get("structured_output")
    if data is None:                     # older CLIs / schema not honoured: the answer is in `result` as text
        data = _loads(out.get("result") or "")
    u = out.get("usage") or {}
    usage = {"input_tokens": sum(u.get(k) or 0 for k in
                                 ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
             "output_tokens": u.get("output_tokens") or 0,
             "cache_read_input_tokens": u.get("cache_read_input_tokens") or 0,
             "cost_usd": out.get("total_cost_usd") or 0.0}
    return data, usage


def _loads(text: str) -> dict:
    """Parse model text as JSON, tolerating a ```json fence or prose around one object."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                pass
    raise LLMUnavailable(f"model did not return JSON: {text.strip()[:200]!r}")

"""What the UI calls: the real pipeline, or fixture bundles when it is absent (dev mode).

The switch lives in pipeline_status() and nowhere else.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from sherpa.config import load_access
from sherpa.contracts import AnalysisPlan, AnswerBundle

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
EVAL_RESULTS = ROOT / "eval" / "results" / "latest.json"

# Words that pick a fixture in fixture mode (plus each fixture's own question words).
FIXTURE_KEYWORDS = {
    "explain_change": "why drop dropped fall fell decline declined change changed drove driver drivers explain",
    "clarify": "what was yesterday",
    "refused": "compare north east west",
    "sql_route": "merchant merchants most failed top highest",
    "reconcile": "settled settlement settlements match gmv reconcile payout payouts",
}
HISTORY_FIXTURES = ("explain_change", "reconcile", "sql_route", "clarify", "refused", "error")
REGIONS = {"north", "south", "east", "west"}
# Demo chips: the planted scenarios' own questions (data/ground_truth_<seed>.json), placeholders until seeded.
DEMO_SCENARIOS = ("S1", "S2", "S3", "S4", "S5b", "S6")
DEMO_FALLBACK = ("Why did success rate drop last week?", "Why did success rate fall on <S2 date>?",
                 "Card success rate fell on <S3 date>: what drove it?",
                 "Why doesn't settled amount match GMV for <S4 date>?")


def seed_of(data_version: str | None) -> int:
    """'seed42-6f9d592f' (DB) or 'v1 · seed 42' -> 42; default 42."""
    m = re.search(r"seed\s*(\d+)", data_version or "")
    return int(m.group(1)) if m else 42


@lru_cache(maxsize=4)
def demo_questions(seed: int = 42) -> tuple[str, ...]:
    try:
        scenarios = json.loads((ROOT / "data" / f"ground_truth_{seed}.json").read_text())["scenarios"]
        by_id = {s["id"]: s["question"] for s in scenarios if isinstance(s.get("question"), str)}
    except (OSError, ValueError, KeyError, TypeError):
        return DEMO_FALLBACK
    return tuple(by_id[i] for i in DEMO_SCENARIOS if i in by_id) or DEMO_FALLBACK


def pipeline_status() -> tuple[Any, str | None]:
    """The one switch: (sherpa.pipeline, None), or (None, why we are in fixture mode)."""
    if os.environ.get("SHERPA_UI_FIXTURES") == "1":
        return None, "SHERPA_UI_FIXTURES=1"
    try:
        from sherpa import pipeline
    except Exception as e:  # noqa: BLE001 - any import failure means dev mode, and the banner says why
        return None, f"sherpa.pipeline is not importable ({type(e).__name__}: {e})"
    return pipeline, None


def answer(question: str, persona: str, plan: AnalysisPlan | None = None,
           on_stage: Callable[[str], None] | None = None,
           on_partial: Callable[[AnswerBundle], None] | None = None) -> AnswerBundle:
    pipe, _ = pipeline_status()
    if pipe is None:
        return fixture_answer(question, persona, plan, on_partial)
    try:
        return pipe.answer(question, persona, plan=plan, on_stage=on_stage, on_partial=on_partial)
    except Exception as e:  # noqa: BLE001 - the contract says answer() never raises; if it does, keep a run id
        return AnswerBundle(run_id=f"ui-{uuid.uuid4().hex[:12]}", question=question, persona=persona,
                            status="error", plan=plan, error=f"{type(e).__name__}: {e}")


def load_fixture(name: str, on_partial: Callable[[AnswerBundle], None] | None = None) -> AnswerBundle:
    """on_partial, as the pipeline calls it: an answered fixture without its headline, claims and confidence."""
    b = AnswerBundle.model_validate_json((FIXTURES / f"{name}.json").read_text())
    if on_partial is not None and b.status == "answered":
        on_partial(b.model_copy(deep=True, update={"headline": None, "claims": [], "confidence": None,
                                                   "confidence_reasons": []}))
    return b


def fixture_runs(persona: str) -> list[AnswerBundle]:
    """Fixture mode's run log (history, permalinks, feedback): the saved bundles of this persona, in a fixed order."""
    return [b for b in map(load_fixture, HISTORY_FIXTURES) if b.persona == persona]


def fixture_name(question: str, persona: str, plan: AnalysisPlan | None = None) -> str:
    """Keyword match. Refusal only when the question names a region the persona cannot see;
    a plan handed back (Explore, clarification, accepted suggestion) is never re-asked or re-refused."""
    words = set(re.findall(r"[a-z]+", f"{question} {plan.intent if plan else ''}".lower()))
    scores = {name: len(words & set(kw.split())) for name, kw in FIXTURE_KEYWORDS.items()}
    visible = {r.lower() for r in load_access().persona(persona).regions}
    if plan is not None or not words & (REGIONS - visible):
        scores.pop("refused")
    if plan is not None:
        scores.pop("clarify")
    best = max(scores, key=lambda k: (scores[k], k == "explain_change"))
    return best if scores[best] else "explain_change"


def fixture_answer(question: str, persona: str, plan: AnalysisPlan | None = None,
                   on_partial: Callable[[AnswerBundle], None] | None = None) -> AnswerBundle:
    return load_fixture(fixture_name(question, persona, plan), on_partial)


def patched(plan: AnalysisPlan, patch: dict[str, Any]) -> AnalysisPlan:
    """Apply a ClarifyOption / Refusal plan_patch: the user has resolved the question, so nothing stays open."""
    d = {**plan.model_dump(), **patch, "ambiguities": [], "clarify_question": None, "refuse_reason": None}
    if d["route"] in ("clarify", "refuse"):
        d["route"] = "catalog"
    return AnalysisPlan.model_validate(d)

"""What the UI calls: the real pipeline, or fixture bundles when it is absent (dev mode).

The switch lives in pipeline_status() and nowhere else.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any

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
    "sql_route": "merchant merchants most failed top",
    "reconcile": "settled settlement settlements match gmv reconcile payout payouts",
}
REGIONS = {"north", "south", "east", "west"}


def pipeline_status() -> tuple[Any, str | None]:
    """The one switch: (sherpa.pipeline, None), or (None, why we are in fixture mode)."""
    if os.environ.get("SHERPA_UI_FIXTURES") == "1":
        return None, "SHERPA_UI_FIXTURES=1"
    try:
        from sherpa import pipeline
    except Exception as e:  # noqa: BLE001 - any import failure means dev mode, and the banner says why
        return None, f"sherpa.pipeline is not importable ({type(e).__name__}: {e})"
    return pipeline, None


def answer(question: str, persona: str, plan: AnalysisPlan | None = None) -> AnswerBundle:
    pipe, _ = pipeline_status()
    if pipe is None:
        return fixture_answer(question, persona, plan)
    try:
        return pipe.answer(question, persona, plan=plan)
    except Exception as e:  # noqa: BLE001 - the contract says answer() never raises; if it does, keep a run id
        return AnswerBundle(run_id=f"ui-{uuid.uuid4().hex[:12]}", question=question, persona=persona,
                            status="error", plan=plan, error=f"{type(e).__name__}: {e}")


def load_fixture(name: str) -> AnswerBundle:
    return AnswerBundle.model_validate_json((FIXTURES / f"{name}.json").read_text())


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


def fixture_answer(question: str, persona: str, plan: AnalysisPlan | None = None) -> AnswerBundle:
    return load_fixture(fixture_name(question, persona, plan))


def patched(plan: AnalysisPlan, patch: dict[str, Any]) -> AnalysisPlan:
    """Apply a ClarifyOption / Refusal plan_patch: the user has resolved the question, so nothing stays open."""
    d = {**plan.model_dump(), **patch, "ambiguities": [], "clarify_question": None, "refuse_reason": None}
    if d["route"] in ("clarify", "refuse"):
        d["route"] = "catalog"
    return AnalysisPlan.model_validate(d)

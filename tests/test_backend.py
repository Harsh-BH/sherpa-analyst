"""app.backend helpers that need no UI: fixture matching, plan patching, seed and demo-question lookup."""
import pytest

from app import backend
from sherpa.contracts import AnalysisPlan


@pytest.mark.parametrize("question,persona,expected", [
    ("Why did success rate drop last week?", "head", "explain_change"),
    ("Card success rate fell on <S3 date>: what drove it?", "head", "explain_change"),
    ("Why doesn't settled amount match GMV for <S4 date>?", "head", "reconcile"),
    ("What was the success rate yesterday?", "head", "clarify"),
    ("Which merchants had the most failed payments last week?", "head", "sql_route"),
    ("Compare North vs South success rate", "rm_south", "refused"),
    ("Compare North vs South success rate", "head", "explain_change"),   # head may see North: nothing to refuse
    ("Is last week's data complete?", "head", "explain_change"),         # no match: the showcase bundle
])
def test_fixture_matching(question, persona, expected):
    assert backend.fixture_name(question, persona) == expected


def test_a_plan_handed_back_is_never_re_asked_or_refused():
    plan = AnalysisPlan(question="q", route="catalog", intent="metric_value", metric="success_rate")
    assert backend.fixture_name("What was the success rate yesterday?", "head", plan) != "clarify"
    assert backend.fixture_name("Compare North vs South success rate", "rm_south", plan) != "refused"


def test_patched_resolves_the_plan():
    c = backend.load_fixture("clarify")
    p = backend.patched(c.plan, c.clarification.options[1].plan_patch)
    assert p.metric == "success_rate_incl_dropoffs" and p.ambiguities == [] and p.route == "catalog"
    r = backend.load_fixture("refused")
    p = backend.patched(r.plan, r.refusal.plan_patch)
    assert p.route == "catalog" and p.refuse_reason is None and p.filters[0].values == ["South"]


@pytest.mark.parametrize("version,seed", [("seed42-6f9d592f", 42), ("v1 · seed 7", 7), (None, 42), ("v2", 42)])
def test_seed_of(version, seed):
    assert backend.seed_of(version) == seed


def test_demo_questions_from_ground_truth(tmp_path, monkeypatch):
    import json
    (tmp_path / "data").mkdir()
    scenarios = [{"id": i, "question": f"question {i}"} for i in ("S6", "S5a", "S5b", "S4", "S3", "S2", "S1")]
    (tmp_path / "data" / "ground_truth_7.json").write_text(json.dumps({"scenarios": scenarios}))
    monkeypatch.setattr(backend, "ROOT", tmp_path)
    backend.demo_questions.cache_clear()
    try:
        assert backend.demo_questions(7) == tuple(f"question {i}" for i in ("S1", "S2", "S3", "S4", "S5b", "S6"))
        assert backend.demo_questions(8) == backend.DEMO_FALLBACK          # no file for that seed
    finally:
        backend.demo_questions.cache_clear()


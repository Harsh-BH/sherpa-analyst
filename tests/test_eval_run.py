import json
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from eval import baseline as bl
from eval import run
from sherpa.contracts import AnswerBundle, Refusal
from tests.test_eval_cases import TRUTH


@pytest.fixture
def env(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "ground_truth_99.json").write_text(json.dumps(TRUTH))
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setattr(run, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(run, "_data_version", lambda: {"version": "seed99-x", "as_of": date(2026, 11, 19)})
    monkeypatch.setattr(run, "_run_query", lambda sql, persona: SimpleNamespace(
        df=pd.DataFrame({"txn_date": [date(2026, 11, 11)]}) if "rank()" in sql else pd.DataFrame({"value": [0.9]})))
    calls = {"answer": 0}

    def answer(question, persona, plan=None):
        calls["answer"] += 1
        return AnswerBundle(run_id="r", question=question, persona=persona, status="refused",
                            refusal=Refusal(reason="The query was stopped by the cost check: big"),
                            timings_ms={"total": 1000}, llm_usage={"cost_usd": 0.001})

    monkeypatch.setattr(run, "_answer", answer)
    monkeypatch.setattr(bl, "_structured", lambda **kw: ({"sql": ""} if "sql" in kw["schema"]["properties"]
                                                         else {"answer": ""}, {"cost_usd": 0.0}))
    return tmp_path, calls


def test_run_seed_writes_contract_shape_and_caches(env):
    tmp, calls = env
    out = run.run_seed(99)
    n = len(out["cases"])
    assert n == 28 and calls["answer"] == n     # 10 known + 6 planted + 4 refusal + 2 clarify + 5 unsafe + 1 injection
    merged = run.merge_files(tmp / "latest.json")
    on_disk = json.loads((tmp / "latest.json").read_text())
    assert on_disk["systems"] == merged["systems"]
    keys = {"result_equivalence", "planted_causes", "refusals", "clarifications", "unsupported_numbers", "p50_ms",
            "cost_usd"}
    assert keys <= set(merged["systems"]["sherpa"]) and keys <= set(merged["systems"]["baseline"])
    assert merged["systems"]["sherpa"]["refusals"] == 1.0          # every stub answer is a cost refusal
    assert merged["systems"]["sherpa"]["result_equivalence"] == 0.0
    assert merged["systems"]["baseline"]["refusals"] == 1.0        # empty SQL = declined
    case = merged["cases"][0]
    assert {"id", "kind", "question", "expected", "sherpa", "baseline", "seed"} <= set(case)
    assert {"pass", "detail"} <= set(case["sherpa"]) and case["id"].endswith("@99")
    assert "display_name" not in json.dumps(merged)                # injected text is not copied into results
    assert "seed 99" in run.scorecard(merged)

    run.run_seed(99, only="refusal")                               # cached: no new pipeline calls
    assert calls["answer"] == n
    assert len(json.loads((tmp / "results" / "seed99.json").read_text())["cases"]) == n   # partial run keeps the rest


def test_truth_version_must_match_db(env, monkeypatch):
    monkeypatch.setattr(run, "_data_version", lambda: {"version": "seed99-OTHER", "as_of": date(2026, 11, 19)})
    with pytest.raises(SystemExit, match="reseed or re-copy"):
        run.run_seed(99)


def test_planted_cause_clarification_takes_the_default_and_asks_again(monkeypatch):
    from sherpa.contracts import AnalysisPlan, Clarification, ClarifyOption
    plan = AnalysisPlan(question="q", route="catalog", intent="explain_change", metric="success_rate")
    opts = [ClarifyOption(label=m, plan_patch={"metric": m, "ambiguities": []}, preview="x")
            for m in ("success_rate", "success_rate_incl_dropoffs")]
    seen = []

    def answer(question, persona, plan=None):
        seen.append(plan)
        if plan is None:
            return AnswerBundle(run_id="r", question=question, persona=persona, status="clarify", plan=plan_,
                                clarification=Clarification(question="which?", options=opts))
        return AnswerBundle(run_id="r", question=question, persona=persona, status="answered", plan=plan)

    plan_ = plan
    monkeypatch.setattr(run, "_answer", answer)
    out = run.run_sherpa({"id": "S3", "kind": "planted_cause", "persona": "head", "question": "q", "expected": {}})
    assert out["followup"] == "success_rate" and seen[1].metric == "success_rate"
    assert out["bundle"]["status"] == "answered"

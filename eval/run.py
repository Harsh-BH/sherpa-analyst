"""Eval runner: Sherpa vs the naive baseline on the planted-cause dataset.

  uv run python -m eval.run                      # every seed in SEED_DBS, each in its own process, merged
  uv run python -m eval.run --seed 42 [--systems sherpa,baseline] [--only known_answer] [--case S1] [--fresh]

A seed run uses the DB named by SHERPA_DB_NAME and data/ground_truth_<seed>.json (their data_version must
match). Case results accumulate in eval/results/seed<N>.json (a partial run replaces only the cases it ran),
and every run re-merges all seed files into --out (default eval/results/latest.json, docs/CONTRACTS.md §7,
plus per-seed sections). LLM-backed outputs are cached per (system, case, data_version) in
eval/results/cache/, so re-grading after a code fix costs nothing; --fresh ignores the cache.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sherpa.config import ROOT
from sherpa.contracts import AnalysisPlan, AnswerBundle

from . import baseline as bl
from .cases import EVAL_DIR, Case, build_cases, gold_sql, grade_sherpa, injection_date, sherpa_unsupported

SEED_DBS = {42: "sherpa", 7: "sherpa_s7"}
RESULTS = EVAL_DIR / "results"
SYSTEMS = ("sherpa", "baseline")
GROUPS = {"result_equivalence": ("known_answer",), "planted_causes": ("planted_cause", "reconciliation", "data_quality"),
          "refusals": ("refusal", "unsafe_sql"), "clarifications": ("clarification",), "injection": ("injection",)}


# ---------------------------------------------------------------- DB / pipeline access (stubbed in tests)
def _answer(question: str, persona: str, plan: AnalysisPlan | None = None) -> AnswerBundle:
    from sherpa.pipeline import answer
    return answer(question, persona, plan=plan)


def _run_query(sql: str, persona: str):
    from sherpa.db import run_query
    return run_query(sql, persona)


def _data_version() -> dict:
    from sherpa.db import data_version
    return data_version("head")


# ---------------------------------------------------------------- running one case
def run_sherpa(case: Case) -> dict[str, Any]:
    """pipeline.answer. When a known-answer or planted-cause case is answered with "which definition?", pick
    the one the gold query uses (planted causes: the plan's own default) as a user would, and ask again.
    The detail records the choice, so an unnecessary question stays visible."""
    plan = AnalysisPlan.model_validate(case["plan"]) if case.get("plan") else None
    b = _answer(case["question"], case["persona"], plan=plan)
    latency, cost, followup = b.timings_ms.get("total", 0), float(b.llm_usage.get("cost_usd") or 0), None
    if case["kind"] in ("known_answer", "planted_cause") and b.status == "clarify" and b.clarification and b.plan:
        want = case["expected"].get("metric") or b.plan.metric
        opt = next((o for o in b.clarification.options if o.plan_patch.get("metric") == want), None)
        if opt:
            followup = opt.label
            b = _answer(case["question"], case["persona"],
                        plan=AnalysisPlan.model_validate(b.plan.model_dump() | opt.plan_patch))
            latency += b.timings_ms.get("total", 0)
            cost += float(b.llm_usage.get("cost_usd") or 0)
    return {"bundle": b.model_dump(mode="json"), "followup": followup, "latency_ms": latency, "cost_usd": cost}


def grade(system: str, case: Case, out: dict, gold) -> dict[str, Any]:
    if system == "sherpa":
        b = AnswerBundle.model_validate(out["bundle"])
        ok, detail = grade_sherpa(case, b, gold)
        if out.get("followup"):
            detail = f"after choosing '{out['followup'][:60]}': {detail}"
        bad = sherpa_unsupported(b, case["question"])
    else:
        ok, detail = bl.grade_baseline(case, out, gold)
        bad = bl.baseline_unsupported(case, out)
    return {"pass": bool(ok), "detail": detail, "unsupported": len(bad), "unsupported_examples": bad[:5],
            "latency_ms": out.get("latency_ms", 0), "cost_usd": round(out.get("cost_usd", 0.0), 5)}


def _cached(system: str, case: Case, version: str, fresh: bool, as_of: str) -> dict:
    key = hashlib.sha256(json.dumps(case, sort_keys=True).encode()).hexdigest()[:10]
    path = RESULTS / "cache" / f"{system}_{case['id']}_{version}_{key}.json"
    if path.exists() and not fresh:
        return json.loads(path.read_text())
    out = run_sherpa(case) if system == "sherpa" else bl.run_baseline(case, as_of=as_of)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, default=str))
    return out


# ---------------------------------------------------------------- a seed
def run_seed(seed: int, *, systems=SYSTEMS, only: str | None = None, case_id: str | None = None,
             fresh: bool = False) -> dict:
    truth = json.loads((ROOT / "data" / f"ground_truth_{seed}.json").read_text())
    dv = _data_version()
    if truth["data_version"] != dv["version"]:
        sys.exit(f"ground_truth_{seed}.json is for {truth['data_version']} but the database "
                 f"(SHERPA_DB_NAME={os.environ.get('SHERPA_DB_NAME', 'sherpa')}) holds {dv['version']}: "
                 f"reseed or re-copy the truth file.")
    s6 = next(s for s in truth["scenarios"] if s["id"] == "S6")["expected"]["merchant_id"]
    cases = [c for c in build_cases(truth, injection_date(s6, _run_query))
             if (only is None or c["kind"] == only) and (case_id is None or c["id"] == case_id)]

    path = RESULTS / f"seed{seed}.json"
    prev = json.loads(path.read_text()) if path.exists() else {}
    results = prev.get("cases", {}) if prev.get("data_version") == dv["version"] else {}
    for c in cases:
        gold = _run_query(gold_sql(c["expected"]["gold"]), "head").df if c["kind"] == "known_answer" else None
        row = results.get(c["id"], {}) | {"id": c["id"], "kind": c["kind"], "persona": c["persona"],
                                         "question": c["question"], "expected": _public(c["expected"])}
        for s in systems:
            t0 = time.perf_counter()
            try:
                row[s] = grade(s, c, _cached(s, c, dv["version"], fresh, str(dv["as_of"])), gold)
            except Exception as e:  # noqa: BLE001 - one broken case must not sink the run; it is recorded as a fail
                row[s] = {"pass": False, "detail": f"{s} error: {type(e).__name__}: {e}"[:300], "unsupported": 0,
                          "latency_ms": int((time.perf_counter() - t0) * 1000), "cost_usd": 0.0}
            print(f"  {c['id']:28s} {s:8s} {'PASS' if row[s]['pass'] else 'fail'}  {row[s]['detail'][:110]}",
                  flush=True)
        results[c["id"]] = row
    out = {"seed": seed, "data_version": dv["version"], "generated_at": _now(), "cases": results}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, default=str))
    return out


def _public(expected: dict) -> dict:
    """Expected values for the UI; the injected display_name is not repeated in the results file."""
    return {k: v for k, v in expected.items() if k != "display_name"}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- scoring and merging
def score(cases: list[dict]) -> dict[str, dict]:
    out = {}
    for s in SYSTEMS:
        rows = [(c["kind"], c[s]) for c in cases if s in c]
        if not rows:
            continue
        m: dict[str, Any] = {}
        for name, kinds in GROUPS.items():
            got = [r["pass"] for k, r in rows if k in kinds]
            m[name] = round(sum(got) / len(got), 3) if got else None
        m["unsupported_numbers"] = sum(r.get("unsupported", 0) for _, r in rows)
        m["p50_ms"] = int(statistics.median(r.get("latency_ms", 0) for _, r in rows))
        m["cost_usd"] = round(sum(r.get("cost_usd", 0) for _, r in rows), 4)
        m["cases"], m["passed"] = len(rows), sum(r["pass"] for _, r in rows)
        out[s] = m
    return out


def merge(seed_runs: list[dict]) -> dict:
    cases = [c | {"id": f"{c['id']}@{r['seed']}", "seed": r["seed"]}
             for r in seed_runs for c in r["cases"].values()]
    return {"generated_at": _now(), "data_version": ", ".join(r["data_version"] for r in seed_runs),
            "systems": score(cases), "cases": cases,
            "seeds": {str(r["seed"]): {"data_version": r["data_version"], "generated_at": r["generated_at"],
                                       "systems": score(list(r["cases"].values()))} for r in seed_runs}}


def merge_files(out_path: Path) -> dict:
    runs = [json.loads(p.read_text()) for p in sorted(RESULTS.glob("seed*.json"))]
    merged = merge(runs)
    out_path.write_text(json.dumps(merged, indent=1, default=str))
    return merged


def scorecard(merged: dict) -> str:
    keys = ["result_equivalence", "planted_causes", "refusals", "clarifications", "injection",
            "unsupported_numbers", "p50_ms", "cost_usd", "passed", "cases"]
    sections = [("all seeds", merged["systems"])] + [(f"seed {k}", v["systems"]) for k, v in merged["seeds"].items()]
    lines = []
    for title, systems in sections:
        lines.append(f"\n{title:22s}" + "".join(f"{s:>12s}" for s in systems))
        for k in keys:
            lines.append(f"  {k:20s}" + "".join(f"{_cell(k, systems[s].get(k)):>12s}" for s in systems))
    fails = [c for c in merged["cases"] if "sherpa" in c and not c["sherpa"]["pass"]]
    lines.append(f"\nSherpa failures ({len(fails)}):")
    lines += [f"  {c['id']:30s} {c['sherpa']['detail'][:140]}" for c in fails] or ["  none"]
    return "\n".join(lines)


def _cell(key: str, v) -> str:
    return "-" if v is None else f"{v:.0%}" if key in GROUPS else f"${v:.3f}" if key == "cost_usd" else str(v)


# ---------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> None:
    os.environ.setdefault("SHERPA_RUN_SOURCE", "eval")   # runs.save_run labels these, the Runs page skips them
    ap = argparse.ArgumentParser(prog="python -m eval.run", description=__doc__.split("\n")[0])
    ap.add_argument("--seed", type=int, help="one seed, against SHERPA_DB_NAME (default: every seed in SEED_DBS)")
    ap.add_argument("--systems", default=",".join(SYSTEMS))
    ap.add_argument("--only", help="case kind, e.g. known_answer")
    ap.add_argument("--case", help="one case id, e.g. S1")
    ap.add_argument("--fresh", action="store_true", help="ignore cached LLM-backed outputs")
    ap.add_argument("--out", type=Path, default=RESULTS / "latest.json")
    a = ap.parse_args(argv)
    if a.seed is None:
        passthrough = [x for x in (argv if argv is not None else sys.argv[1:]) if x != "--seed"]
        for seed, db in SEED_DBS.items():
            print(f"== seed {seed} on {db}", flush=True)
            subprocess.run([sys.executable, "-m", "eval.run", "--seed", str(seed), *passthrough],
                           env=os.environ | {"SHERPA_DB_NAME": db}, cwd=ROOT, check=True)
    else:
        run_seed(a.seed, systems=tuple(a.systems.split(",")), only=a.only, case_id=a.case, fresh=a.fresh)
    merged = merge_files(a.out)
    print(scorecard(merged))
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()

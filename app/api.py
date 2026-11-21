"""The JSON/SSE service the Next.js UI talks to. Thin: every number and sentence comes from sherpa/ and app.view."""
from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Iterator, Literal, get_args

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from app import backend
from app.explore import ExploreForm, build_explore_plan
from app.view import KV, STAGES, View, build_view, fmt_ms
from sherpa.config import load_access, load_catalog, settings
from sherpa.contracts import AnalysisPlan, AnswerBundle, Intent, WindowPreset

app = FastAPI(title="Sherpa API")

DEFAULT_PERSONA = "head"
REFUSAL_DEMO = {"question": "Compare North vs South success rate", "persona": "rm_south"}
EVAL_METRICS = [  # key, label, format
    ("result_equivalence", "Result equivalence", "pct"), ("planted_causes", "Planted causes found", "pct"),
    ("refusals", "Correct refusals", "pct"), ("clarifications", "Correct clarifications", "pct"),
    ("unsupported_numbers", "Unsupported numbers", "int"), ("p50_ms", "p50 latency", "ms"), ("cost_usd", "LLM cost", "usd"),
]


def _fmt(v: Any, fmt: str) -> str:
    if not isinstance(v, int | float):   # missing or malformed in the results file: show it, don't crash
        return "n/a" if v is None else str(v)
    return {"pct": f"{v:.0%}", "int": f"{v:,.0f}", "ms": f"{v / 1000:.1f} s", "usd": f"${v:.2f}"}[fmt]


def _words(s: str) -> str:
    return s.replace("_", " ")


# ------------------------------------------------------------------ models
class Health(BaseModel):
    ok: bool
    fixture_mode: bool
    fixture_reason: str | None


class PersonaInfo(BaseModel):
    key: str
    label: str
    regions: list[str]


class DemoItem(BaseModel):
    question: str
    persona: str | None


class Option(BaseModel):
    value: str
    label: str


class MetricInfo(BaseModel):
    name: str
    label: str
    table: str


class DimensionInfo(BaseModel):
    name: str
    label: str
    tables: list[str]
    values: list[str]


class CatalogInfo(BaseModel):
    intents: list[Option]
    metrics: list[MetricInfo]
    dimensions: list[DimensionInfo]
    windows: list[Option]
    grains: list[str]


class Meta(BaseModel):
    personas: list[PersonaInfo]
    default_persona: str
    demo: list[DemoItem]
    verified: list[str]
    catalog: CatalogInfo
    llm_backend: str
    data_version: str | None
    as_of: str | None
    fixture_mode: bool


class AskRequest(BaseModel):
    question: str
    persona: str
    plan: AnalysisPlan | None = None
    patch: dict | None = None
    fixture: str | None = None

    @field_validator("question")
    @classmethod
    def _question(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 500:
            raise ValueError("question must be 1 to 500 characters")
        return v

    @field_validator("persona")
    @classmethod
    def _persona(cls, v: str) -> str:
        if v not in load_access().personas:
            raise ValueError(f"unknown persona {v!r}")
        return v


class ExplorePlan(BaseModel):
    question: str
    plan: AnalysisPlan


class EvalTile(BaseModel):
    label: str
    sherpa: str
    baseline: str


class EvalCase(BaseModel):
    id: str | None
    kind: str | None
    question: str | None
    sherpa_pass: bool
    sherpa_detail: str | None
    baseline_pass: bool
    baseline_detail: str | None


class EvalOk(BaseModel):
    status: Literal["ok"] = "ok"
    fixture: bool
    generated_at: str | None
    data_version: str | None
    tiles: list[EvalTile]
    cases: list[EvalCase]


class EvalMissing(BaseModel):
    status: Literal["missing"] = "missing"
    path: str


class EvalError(BaseModel):
    status: Literal["error"] = "error"
    message: str


class RunRow(BaseModel):
    run_id: str
    asked_at: str
    persona: str
    question: str
    status: str
    route: str
    confidence: str
    total: str
    cost: str
    footprint: list[KV]


class RunsOk(BaseModel):
    status: Literal["ok"] = "ok"
    tiles: list[KV]
    recent: list[RunRow]


class RunsUnavailable(BaseModel):
    status: Literal["unavailable"] = "unavailable"
    message: str


# ------------------------------------------------------------------ routes
@app.get("/api/health")
def health() -> Health:
    pipe, reason = backend.pipeline_status()
    return Health(ok=True, fixture_mode=pipe is None, fixture_reason=reason)


@app.get("/api/meta")
def meta() -> Meta:
    access, catalog = load_access(), load_catalog()
    data_version = as_of = None
    try:
        v = _data_version(DEFAULT_PERSONA)
        data_version, as_of = v["version"], f"{v['as_of']:%d %b %Y}"
    except Exception:  # noqa: BLE001 - no DB: the sidebar shows a dash, the page still loads
        pass
    seed = backend.seed_of(data_version)
    return Meta(
        personas=[PersonaInfo(key=k, label=p.label, regions=p.regions) for k, p in access.personas.items()],
        default_persona=DEFAULT_PERSONA,
        demo=[DemoItem(question=q, persona=None) for q in backend.demo_questions(seed)] + [DemoItem(**REFUSAL_DEMO)],
        verified=[vq.question for vq in catalog.verified_queries],
        catalog=CatalogInfo(
            intents=[Option(value=i, label=_words(i).capitalize()) for i in get_args(Intent)],
            metrics=[MetricInfo(name=m.name, label=m.label, table=m.table) for m in catalog.metrics],
            dimensions=[DimensionInfo(name=d.name, label=d.label, tables=d.tables, values=d.values or [])
                        for d in catalog.dimensions],
            windows=[Option(value=w, label=_words(w)) for w in get_args(WindowPreset)],
            grains=["day", "hour"]),
        llm_backend=settings().llm_backend, data_version=data_version, as_of=as_of,
        fixture_mode=backend.pipeline_status()[0] is None)


def _data_version(persona: str) -> dict:
    from sherpa import db
    return db.data_version(persona)


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


def _run(req: AskRequest, plan: AnalysisPlan | None, fixture: str | None, q: queue.Queue, t0: float) -> None:
    """The pipeline thread: stages and then the bundle go onto q."""
    def on_stage(name: str) -> None:
        q.put(("stage", {"name": name, "t_ms": round((time.perf_counter() - t0) * 1000)}))
    try:
        bundle = backend.load_fixture(fixture) if fixture else backend.answer(req.question, req.persona, plan, on_stage)
    except Exception as e:  # noqa: BLE001 - keep a run id, as backend.answer does
        bundle = AnswerBundle(run_id=f"ui-{uuid.uuid4().hex[:12]}", question=req.question, persona=req.persona,
                              status="error", plan=plan, error=f"{type(e).__name__}: {e}")
    q.put(("result", bundle))


def _stream(req: AskRequest, plan: AnalysisPlan | None, fixture: str | None) -> Iterator[str]:
    q: queue.Queue = queue.Queue()
    threading.Thread(target=_run, args=(req, plan, fixture, q, time.perf_counter()), daemon=True).start()
    while True:
        kind, payload = q.get()
        if kind == "stage":
            yield _sse("stage", json.dumps(payload))
            continue
        yield _sse("result", f'{{"bundle":{payload.model_dump_json()},"view":{build_view(payload).model_dump_json()}}}')
        return


@app.post("/api/ask", response_class=StreamingResponse, responses={200: {"content": {"text/event-stream": {}}}})
def ask(req: AskRequest) -> StreamingResponse:
    plan = req.plan
    if req.patch is not None:
        if plan is None:
            raise HTTPException(422, "patch needs a plan")
        try:
            plan = backend.patched(plan, req.patch)
        except ValueError as e:
            raise HTTPException(422, f"patch does not give a valid plan: {e}") from None
    fixture = None
    if req.fixture is not None:
        path = backend.FIXTURES / f"{req.fixture}.json"
        if req.fixture == "eval_latest" or "/" in req.fixture or not path.is_file():
            raise HTTPException(422, f"unknown fixture {req.fixture!r}")
        if backend.pipeline_status()[0] is None:   # honoured only in fixture mode
            fixture = req.fixture
    return StreamingResponse(_stream(req, plan, fixture), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@app.post("/api/explore/plan")
def explore_plan(form: ExploreForm) -> ExplorePlan:
    try:
        question, plan = build_explore_plan(form)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return ExplorePlan(question=question, plan=plan)


@app.get("/api/eval")
def eval_results() -> EvalOk | EvalMissing | EvalError:
    path, fixture = backend.EVAL_RESULTS, False
    if not path.exists() and backend.pipeline_status()[0] is None:
        path, fixture = backend.FIXTURES / "eval_latest.json", True
    try:
        data = json.loads(path.read_text())
        systems, cases = data["systems"], data.get("cases", [])
        sherpa, base = systems.get("sherpa", {}), systems.get("baseline", {})
        return EvalOk(
            fixture=fixture, generated_at=data.get("generated_at"), data_version=data.get("data_version"),
            tiles=[EvalTile(label=label, sherpa=_fmt(sherpa.get(k), f), baseline=_fmt(base.get(k), f))
                   for k, label, f in EVAL_METRICS],
            cases=[EvalCase(id=c.get("id"), kind=c.get("kind"), question=c.get("question"),
                            sherpa_pass=bool(c.get("sherpa", {}).get("pass")), sherpa_detail=c.get("sherpa", {}).get("detail"),
                            baseline_pass=bool(c.get("baseline", {}).get("pass")),
                            baseline_detail=c.get("baseline", {}).get("detail")) for c in cases])
    except FileNotFoundError:
        return EvalMissing(path=str(path.relative_to(backend.ROOT)) if path.is_relative_to(backend.ROOT) else str(path))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        return EvalError(message=f"Could not read {path.name}: {type(e).__name__}: {e}")


def _run_row(r: dict) -> RunRow:
    t, u = r.get("timings_ms") or {}, r.get("llm_usage") or {}
    cost = u.get("cost_usd")
    asked = r.get("asked_at")
    footprint = [KV(label="LLM", value=str(u.get("backend") or "n/a"))]
    footprint += [KV(label=s, value=fmt_ms(t[s])) for s in STAGES if s in t]
    return RunRow(run_id=str(r.get("run_id")), asked_at=f"{asked:%d %b %Y %H:%M}" if isinstance(asked, datetime) else str(asked),
                  persona=str(r.get("persona")), question=str(r.get("question")), status=str(r.get("status")),
                  route=str(r.get("route") or "n/a"), confidence=str(r.get("confidence") or "n/a"),
                  total=fmt_ms(t.get("total")), cost=_fmt(cost, "usd"), footprint=footprint)


@app.get("/api/runs")
def runs() -> RunsOk | RunsUnavailable:
    try:
        from sherpa import runs as run_log
        stats, recent = run_log.run_stats(), run_log.recent_runs(50)
    except Exception as e:  # noqa: BLE001 - no DB / no runs module: say so instead of failing the page
        detail = str(e).splitlines()[0] if str(e) else "no detail"
        return RunsUnavailable(message=f"Run history is unavailable ({type(e).__name__}: {detail}). "
                                       "It needs the seeded database and sherpa.runs.")
    tiles = [("Runs", "runs", "int"), ("p50 latency", "p50_ms", "ms"), ("p95 latency", "p95_ms", "ms"),
             ("LLM cost", "llm_cost_usd", "usd"), ("Refusal rate", "refusal_rate", "pct"),
             ("Clarify rate", "clarify_rate", "pct"), ("Cache hit rate", "cache_hit_rate", "pct")]
    return RunsOk(tiles=[KV(label=label, value=_fmt(stats.get(k), f)) for label, k, f in tiles],
                  recent=[_run_row(r) for r in recent])

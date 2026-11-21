"""The JSON/SSE service the Next.js UI talks to. Thin: every number and sentence comes from sherpa/ and app.view."""
from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from collections import Counter
from datetime import datetime
from statistics import mean
from typing import Any, Iterator, Literal, get_args
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from app import backend, overview as home
from app.explore import ExploreForm, build_explore_plan
from app.overview import DataHealth, OverviewOk, OverviewUnavailable
from app.view import KV, STAGE_LABELS, STAGES, ChartView, View, build_view, fmt_ms
from sherpa import charts
from sherpa.config import load_access, load_catalog, settings
from sherpa.contracts import AnalysisPlan, AnswerBundle, Intent, WindowPreset

app = FastAPI(title="Sherpa API")

DEFAULT_PERSONA = "head"
# The Next.js rewrite proxy destroys a socket idle for 30 s (experimental.proxyTimeout), and one stage can run
# minutes (llm.TIMEOUT_S = 180 per call, plus a repair call): an SSE comment this often keeps the stream alive.
KEEPALIVE_S = 15
REFUSAL_DEMO = {"question": "Compare North vs South success rate", "persona": "rm_south"}
EVAL_METRICS = [  # key, label, format
    ("result_equivalence", "Result equivalence", "pct"), ("planted_causes", "Planted causes found", "pct"),
    ("refusals", "Correct refusals", "pct"), ("clarifications", "Correct clarifications", "pct"),
    ("unsupported_numbers", "Unsupported numbers", "int"), ("p50_ms", "p50 latency", "ms"), ("cost_usd", "LLM cost", "usd"),
]
SYSTEMS = {"Sherpa": charts.MIX, "Baseline": charts.GREY}   # eval system label -> chart colour
PCT_AXIS = {"title": None, "format": ".0%", "values": [0, 0.25, 0.5, 0.75, 1]}
IST = ZoneInfo("Asia/Kolkata")
FEEDBACK = {1: "up", -1: "down"}   # app.run_feedback.rating -> RunRow.feedback


def _fmt(v: Any, fmt: str) -> str:
    if not isinstance(v, int | float):   # missing or malformed in the results file: show it, don't crash
        return "n/a" if v is None else str(v)
    return {"pct": f"{v:.0%}", "int": f"{v:,.0f}", "ms": f"{v / 1000:.1f} s", "usd": f"${v:.2f}"}[fmt]


def _words(s: str) -> str:
    return s.replace("_", " ")


def _kind(s: str) -> str:
    """Eval case kind as a label: 'unsafe_sql' -> 'Unsafe SQL' (str.capitalize would lowercase the acronym)."""
    w = " ".join("SQL" if x == "sql" else x for x in s.split("_"))
    return w[:1].upper() + w[1:]


def _when(iso: Any) -> str | None:
    """An ISO timestamp from the eval results as IST wall-clock text; anything unparseable passes through."""
    try:
        t = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso
    return f"{_local(t):%d %b %Y %H:%M} IST" if t.tzinfo else f"{t:%d %b %Y %H:%M}"


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


class AskResult(BaseModel):
    """The data of the stream's one `result` event."""
    bundle: AnswerBundle
    view: View
    feedback: Literal["up", "down"] | None = None   # a reopened run's latest thumb (GET /api/runs/{id})


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
    charts: list[ChartView]
    proof: str | None = None   # the home rail's one-line result; None without cases


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
    feedback: Literal["up", "down"] | None = None   # the latest thumb, if any


class RunsOk(BaseModel):
    status: Literal["ok"] = "ok"
    tiles: list[KV]
    recent: list[RunRow]
    charts: list[ChartView]   # empty when there are no app runs


class RunsUnavailable(BaseModel):
    status: Literal["unavailable"] = "unavailable"
    message: str


class HistoryItem(BaseModel):
    """A run the persona can reopen with GET /api/runs/{run_id}."""
    run_id: str
    question: str
    status: str
    confidence: str | None
    asked_at: str   # formatted, IST ('fixture' in fixture mode)


class FeedbackRequest(BaseModel):
    persona: str
    rating: Literal[-1, 1]


class FeedbackSaved(BaseModel):
    run_id: str
    feedback: Literal["up", "down"]


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
        t_ms = round((time.perf_counter() - t0) * 1000)
        q.put(("stage", {"name": name, "t_ms": t_ms, "elapsed": fmt_ms(t_ms)}))

    def on_partial(b: AnswerBundle) -> None:
        q.put(("partial", b))
    try:
        bundle = (backend.load_fixture(fixture, on_partial) if fixture
                  else backend.answer(req.question, req.persona, plan, on_stage, on_partial))
    except Exception as e:  # noqa: BLE001 - keep a run id, as backend.answer does
        bundle = AnswerBundle(run_id=f"ui-{uuid.uuid4().hex[:12]}", question=req.question, persona=req.persona,
                              status="error", plan=plan, error=f"{type(e).__name__}: {e}")
    q.put(("result", bundle))


def _stream(req: AskRequest, plan: AnalysisPlan | None, fixture: str | None) -> Iterator[str]:
    q: queue.Queue = queue.Queue()
    threading.Thread(target=_run, args=(req, plan, fixture, q, time.perf_counter()), daemon=True).start()
    while True:
        try:
            kind, payload = q.get(timeout=KEEPALIVE_S)
        except queue.Empty:
            yield ": keepalive\n\n"   # the client parser skips blocks with no event
            continue
        if kind == "stage":
            yield _sse("stage", json.dumps(payload))
            continue
        if kind == "partial":
            try:   # the numbers before the narrative; optional, so one that cannot be viewed is dropped, never fatal
                yield _sse("partial", AskResult(bundle=payload, view=build_view(payload, partial=True)).model_dump_json())
            except Exception:  # noqa: BLE001
                pass
            continue
        yield _sse("result", AskResult(bundle=payload, view=build_view(payload)).model_dump_json())
        return


@app.post("/api/ask", response_class=StreamingResponse, responses={200: {
    "model": AskResult, "content": {"text/event-stream": {}},
    "description": "SSE: `stage` events {name, t_ms, elapsed} as stages start; at most one `partial` event (an AskResult "
                   "with view.partial=true: the numbers, no headline, claims or confidence, and bundle.status not final) "
                   "after the dq stage; then one `result` event whose data is AskResult."}})
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
        if req.fixture in ("eval_latest", "overview", "data_health") or "/" in req.fixture or not path.is_file():
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
        rows = [EvalCase(id=c.get("id"), kind=c.get("kind"), question=c.get("question"),
                         sherpa_pass=bool(c.get("sherpa", {}).get("pass")), sherpa_detail=c.get("sherpa", {}).get("detail"),
                         baseline_pass=bool(c.get("baseline", {}).get("pass")),
                         baseline_detail=c.get("baseline", {}).get("detail")) for c in cases]
        n = len(rows)
        return EvalOk(
            fixture=fixture, generated_at=_when(data.get("generated_at")), data_version=data.get("data_version"),
            tiles=[EvalTile(label=label, sherpa=_fmt(sherpa.get(k), f), baseline=_fmt(base.get(k), f))
                   for k, label, f in EVAL_METRICS],
            cases=rows, charts=_eval_charts(sherpa, base, cases),
            proof=f"Eval: {sum(c.sherpa_pass for c in rows)}/{n} cases vs {sum(c.baseline_pass for c in rows)}/{n} "
                  "for a naive baseline" if n else None)
    except FileNotFoundError:
        return EvalMissing(path=str(path.relative_to(backend.ROOT)) if path.is_relative_to(backend.ROOT) else str(path))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        return EvalError(message=f"Could not read {path.name}: {type(e).__name__}: {e}")


def _vs_summary(title: str, rows: list[dict], y: str) -> str:
    """'<title>: <y> <sherpa> vs <baseline>, ...' from grouped-bar rows."""
    by: dict[str, dict[str, str]] = {}
    for r in rows:
        by.setdefault(r[y], {})[r["system"]] = r["_label"]
    return f"{title}: " + ", ".join(f"{k} {v.get('Sherpa', 'n/a')} vs {v.get('Baseline', 'n/a')}" for k, v in by.items()) + "."


def _eval_charts(sherpa: dict, base: dict, cases: list[dict]) -> list[ChartView]:
    systems = {"Sherpa": sherpa, "Baseline": base}
    rates = [{"metric": label, "system": s, "rate": v, "_label": _fmt(v, "pct")}
             for k, label, _ in EVAL_METRICS[:4] for s in SYSTEMS
             if isinstance(v := systems[s].get(k), int | float) and not isinstance(v, bool)]
    kinds = Counter(c.get("kind") or "other" for c in cases)
    by_kind = []
    for kind, n in kinds.most_common():
        for s in SYSTEMS:
            graded = [c[s.lower()] for c in cases if (c.get("kind") or "other") == kind and isinstance(c.get(s.lower()), dict)]
            if graded:
                r = sum(bool(g.get("pass")) for g in graded) / len(graded)
                by_kind.append({"kind": f"{_kind(kind)} (n={n})", "system": s, "rate": r, "_label": _fmt(r, "pct")})
    out = []
    for key, title, rows, y in (("eval-vs-baseline", "Sherpa vs baseline", rates, "metric"),
                                ("eval-by-kind", "Pass rate by question type", by_kind, "kind")):
        if rows:
            out.append(ChartView(key=key, title=title, summary=_vs_summary(title, rows, y),
                                 spec=charts.hbars(rows, y, "rate", title, PCT_AXIS, SYSTEMS, group="system", x_max=1)))
    return out


def _local(t: Any) -> datetime | Any:
    return t.astimezone(IST) if isinstance(t, datetime) and t.tzinfo else t


def _runs_charts(series: list[dict]) -> list[ChartView]:
    """The Runs page charts from run_series() (app runs, oldest first); none when there are no runs."""
    if not series:
        return []
    rows = []
    for r in series:
        t, cost = r.get("timings_ms") or {}, r.get("cost_usd")
        rows.append({"t": _local(r["asked_at"]).replace(tzinfo=None).isoformat(timespec="seconds"),
                     "status": str(r["status"]), "total": t.get("total"), "timings": t,
                     "cost": cost if isinstance(cost, int | float) else None})
    span = _local(series[-1]["asked_at"]) - _local(series[0]["asked_at"])
    hourly = span.total_seconds() <= 2 * 86400
    x_format = "%d %b %H:%M" if hourly else "%d %b"
    by_status = Counter(r["status"] for r in rows)
    out = [ChartView(
        key="runs-over-time", title="Runs over time",
        summary=f"{len(rows)} runs: " + ", ".join(f"{by_status[s]} {s}" for s in charts.STATUS)
                + f", {'by hour' if hourly else 'by day'}.",
        spec=charts.status_bars([{"t": r["t"], "status": r["status"]} for r in rows], "t",
                                "yearmonthdatehours" if hourly else "yearmonthdate", "Runs over time"))]
    means = [(STAGE_LABELS[s], mean(v)) for s in STAGES
             if (v := [r["timings"][s] for r in rows if isinstance(r["timings"].get(s), int | float)])]
    if means:
        title = "Where the time goes"
        out.append(ChartView(
            key="stage-time", title=title,
            summary=f"{title}, mean per run: " + ", ".join(f"{s} {fmt_ms(ms)}" for s, ms in means) + ".",
            spec=charts.hbars([{"stage": s, "ms": ms, "_label": fmt_ms(ms)} for s, ms in means], "stage", "ms", title,
                              {"title": "Mean time per run", "tickCount": 4, "labelOverlap": "greedy", "labelExpr": "format(datum.value / 1000, '.1~f') + ' s'"},
                              {"Mean": charts.MIX})))
    timed = [r for r in rows if isinstance(r["total"], int | float)]
    if timed:
        fast, slow = min(r["total"] for r in timed), max(r["total"] for r in timed)
        out.append(ChartView(
            key="latency", title="Latency by run",
            summary=f"Latency by run: {len(timed)} runs, fastest {fmt_ms(fast)}, slowest {fmt_ms(slow)}.",
            spec=charts.status_points([{"t": r["t"], "status": r["status"], "seconds": r["total"] / 1000,
                                        "_label": fmt_ms(r["total"])} for r in timed], "t", "seconds", "Latency by run",
                                      {"title": "Total time (s)"}, x_format)))
    spend, cum = [], 0.0
    for r in rows:
        if r["cost"] is not None:
            cum += r["cost"]
            spend.append({"t": r["t"], "series": "LLM spend", "usd": cum, "_label": f"${cum:.4f}"})
    if spend:
        out.append(ChartView(
            key="llm-spend", title="LLM spend",
            summary=f"LLM spend: {spend[-1]['_label']} in total over {len(spend)} runs with a recorded cost.",
            spec=charts.lines(spend, "t", "usd", "LLM spend", {"title": "USD, cumulative", "format": "$.3~f"},
                              {"LLM spend": charts.MIX}, zero=True, x_format=x_format)))
    return out


def _run_row(r: dict) -> RunRow:
    t, u = r.get("timings_ms") or {}, r.get("llm_usage") or {}
    cost = u.get("cost_usd")
    asked = _local(r.get("asked_at"))   # IST, like the charts
    footprint = [KV(label="LLM", value=str(u.get("backend") or "n/a"))]
    footprint += [KV(label=s, value=fmt_ms(t[s])) for s in STAGES if s in t]
    return RunRow(run_id=str(r.get("run_id")), asked_at=f"{asked:%d %b %Y %H:%M}" if isinstance(asked, datetime) else str(asked),
                  persona=str(r.get("persona")), question=str(r.get("question")), status=str(r.get("status")),
                  route=str(r.get("route") or "n/a"), confidence=str(r.get("confidence") or "n/a"),
                  total=fmt_ms(t.get("total")), cost=_fmt(cost, "usd"), footprint=footprint,
                  feedback=FEEDBACK.get(r.get("rating")))


@app.get("/api/runs")
def runs() -> RunsOk | RunsUnavailable:
    try:
        from sherpa import runs as run_log
        stats, recent, series = run_log.run_stats(), run_log.recent_runs(50), run_log.run_series()
    except Exception as e:  # noqa: BLE001 - no DB / no runs module: say so instead of failing the page
        detail = str(e).splitlines()[0] if str(e) else "no detail"
        return RunsUnavailable(message=f"Run history is unavailable ({type(e).__name__}: {detail}). "
                                       "It needs the seeded database and sherpa.runs.")
    tiles = [("Runs", "runs", "int"), ("p50 latency", "p50_ms", "ms"), ("p95 latency", "p95_ms", "ms"),
             ("LLM cost", "llm_cost_usd", "usd"), ("Refusal rate", "refusal_rate", "pct"),
             ("Clarify rate", "clarify_rate", "pct"), ("Cache hit rate", "cache_hit_rate", "pct"),
             ("Helpful", "helpful_rate", "pct")]
    return RunsOk(tiles=[KV(label=label, value=_fmt(stats.get(k), f)) for label, k, f in tiles],
                  recent=[_run_row(r) for r in recent], charts=_runs_charts(series))


@app.get("/api/overview", responses={422: {"description": "Unknown persona"}})
def overview(persona: str = DEFAULT_PERSONA) -> OverviewOk | OverviewUnavailable:
    """Home: last 30 days vs the 30 before, governed queries as the persona. Never fails: unavailable says why."""
    return _home_panel(persona, OverviewOk, "overview", lambda: home.build(persona))


@app.get("/api/data-health", responses={422: {"description": "Unknown persona"}})
def data_health(persona: str = DEFAULT_PERSONA) -> DataHealth | OverviewUnavailable:
    """The home rail's data health: the governed dq checks over the last 30 days, as the persona."""
    return _home_panel(persona, DataHealth, "data_health", lambda: home.data_health(persona))


def _home_panel(persona: str, model: type[OverviewOk] | type[DataHealth], fixture: str, build: Any) -> Any:
    if persona not in load_access().personas:
        raise HTTPException(422, f"unknown persona {persona!r}")
    try:
        if backend.pipeline_status()[0] is None:   # fixture mode: captured from the real endpoint for one persona
            o = model.model_validate_json((backend.FIXTURES / f"{fixture}.json").read_text())
            # another persona's scope differs: hide the panel rather than show the fixture persona's numbers
            return o if o.persona == persona else OverviewUnavailable(reason=f"fixture captured for {o.persona} only")
        return build()
    except Exception as e:  # noqa: BLE001 - no DB, no seed, a guard or cost rejection: the UI hides the panel
        detail = str(e).splitlines()[0] if str(e) else "no detail"
        return OverviewUnavailable(reason=f"{type(e).__name__}: {detail}")


# ------------------------------------------------------------------ history, permalinks, feedback
# Persona scope is the boundary: a run of another persona, a missing run and a run without a saved bundle all
# give the same bare 404. Fixture mode reads backend.fixture_runs and stores nothing.
def _fixture_run(run_id: str, persona: str) -> AnswerBundle | None:
    return next((b for b in backend.fixture_runs(persona) if b.run_id == run_id), None)


def _no_such_run(run_id: str, persona: str) -> bool:
    """An unknown persona, or an id Postgres cannot even compare (a NUL byte), is just another run not found."""
    return "\x00" in run_id or persona not in load_access().personas


@app.get("/api/history", responses={422: {"description": "Unknown persona"}})
def history(persona: str, limit: int = Query(20, ge=1, le=50)) -> list[HistoryItem]:
    """The persona's own app runs that can be reopened, newest first."""
    if persona not in load_access().personas:
        raise HTTPException(422, f"unknown persona {persona!r}")
    if backend.pipeline_status()[0] is None:
        return [HistoryItem(run_id=b.run_id, question=b.question, status=b.status, confidence=b.confidence,
                            asked_at="fixture") for b in backend.fixture_runs(persona)][:limit]
    from sherpa import runs as run_log
    return [HistoryItem(run_id=r["run_id"], question=r["question"], status=r["status"], confidence=r["confidence"],
                        asked_at=f"{_local(r['asked_at']):%d %b %Y %H:%M}") for r in run_log.history(persona, limit)]


@app.get("/api/runs/{run_id}", responses={404: {"description": "No such run for this persona"}})
def get_run(run_id: str, persona: str) -> AskResult:
    """A saved run as the same AskResult /api/ask streams, its view rebuilt from the stored bundle."""
    if _no_such_run(run_id, persona):
        raise HTTPException(404)
    if backend.pipeline_status()[0] is None:
        bundle, rating = _fixture_run(run_id, persona), None   # fixture mode stores no ratings
    else:
        from sherpa import runs as run_log
        bundle = run_log.get_run(run_id, persona)
        rating = bundle and run_log.latest_rating(run_id, persona)
    if bundle is None:
        raise HTTPException(404)
    return AskResult(bundle=bundle, view=build_view(bundle), feedback=FEEDBACK.get(rating))


@app.post("/api/runs/{run_id}/feedback", responses={404: {"description": "No such run for this persona"}})
def run_feedback(run_id: str, req: FeedbackRequest) -> FeedbackSaved:
    """Thumbs up (1) or down (-1). Insert-only: the latest rating wins when read."""
    if _no_such_run(run_id, req.persona):
        raise HTTPException(404)
    if backend.pipeline_status()[0] is None:
        found = _fixture_run(run_id, req.persona) is not None
    else:
        from sherpa import runs as run_log
        found = run_log.save_feedback(run_id, req.persona, req.rating)
    if not found:
        raise HTTPException(404)
    return FeedbackSaved(run_id=run_id, feedback=FEEDBACK[req.rating])

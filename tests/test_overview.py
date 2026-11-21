"""Home overview honesty: its numbers are the governed pipeline's numbers for the same metric, window and persona."""
import pytest
from fastapi.testclient import TestClient

from app import overview
from app.api import app
from sherpa import db
from sherpa.compiler import compile_metric, metric_value, resolve_window
from sherpa.contracts import TimeWindow, format_value

pytestmark = pytest.mark.db


def _independent(metric: str, persona: str) -> float:
    v = db.data_version(persona)
    w = resolve_window(TimeWindow(preset="last_30_days"), v["as_of"], v["data_start"])
    df = db.run_query(compile_metric(metric, window=w), persona, use_cache=False).df
    return metric_value(metric, df.num.sum(), df.den.sum())


@pytest.mark.parametrize("persona", ["head", "rm_south"])
def test_overview_success_rate_equals_the_governed_query(persona, monkeypatch):
    want = _independent("success_rate", persona)
    v = db.data_version(persona)
    _, _, nums = overview.numbers(persona, v["as_of"], v["data_start"])
    assert nums["success_rate"]["value"] == pytest.approx(want, rel=0, abs=1e-12)
    monkeypatch.delenv("SHERPA_UI_FIXTURES", raising=False)
    o = TestClient(app).get(f"/api/overview?persona={persona}").json()
    assert o["available"] is True and o["persona"] == persona
    kpi = {k["key"]: k for k in o["kpis"]}
    assert kpi["success_rate"]["value"] == format_value(want, "pct")
    assert kpi["gmv"]["value"] == format_value(_independent("gmv", persona), "inr")


def test_overview_scope_differs_by_persona():
    head, south = overview.build("head"), overview.build("rm_south")
    assert head.kpis[1].value != south.kpis[1].value          # GMV: South is a slice of all regions
    assert overview.build("head") is head                     # cached per (persona, data_version)

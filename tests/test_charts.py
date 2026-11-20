"""Chart specs: valid Vega-Lite, expected encodings, labels on every bar. Built from the fixture bundles."""
import json
from functools import lru_cache
from pathlib import Path

import altair
import jsonschema
import pytest

from sherpa import charts
from sherpa.contracts import AnswerBundle

FIXTURES = Path(__file__).parent / "fixtures"


@lru_cache(maxsize=1)
def validator():
    # The newest Vega-Lite schema available offline (altair ships v6); our v5 specs must also be valid there.
    schema = json.loads((Path(altair.__file__).parent / "vegalite/v6/schema/vega-lite-schema.json").read_text())
    return jsonschema.Draft7Validator(schema)


def bundle(name: str) -> AnswerBundle:
    return AnswerBundle.model_validate_json((FIXTURES / f"{name}.json").read_text())


def valid(spec: dict) -> dict:
    errors = [e.message for e in validator().iter_errors(spec)]
    assert not errors, errors[:3]
    json.dumps(spec)  # JSON-serialisable, so st.vega_lite_chart and the run bundle can carry it
    assert spec["$schema"].endswith("v5.json") and spec["title"]
    return spec


def layers(spec: dict) -> list[dict]:
    return spec.get("layer", [spec])


def has_text_labels(spec: dict) -> bool:
    return any(layer["mark"]["type"] == "text" and layer["encoding"]["text"]["field"] == "_label" for layer in layers(spec))


def test_waterfall_simpson_example():
    dec = bundle("explain_change").drivers.dimensions[0]
    spec = valid(charts.waterfall(dec))
    rows = {r["step"]: r for r in spec["data"]["values"]}
    assert list(rows)[-3:] == ["Mix total", "Rate total", "Change (Δ)"]
    assert rows["Mix total"]["_label"] == "-1.60 pp" and rows["Rate total"]["_label"] == "+0.50 pp"
    assert rows["Change (Δ)"]["_label"] == "-1.10 pp"
    steps = [r for r in spec["data"]["values"] if r["kind"] != "Total"]
    assert {r["kind"] for r in steps} == {"Mix effect", "Rate effect"}
    assert steps[-1]["end"] == pytest.approx(dec.delta)          # the chain lands on the total change
    bar = layers(spec)[0]["encoding"]
    assert bar["x"]["field"] == "start" and bar["x2"]["field"] == "end" and bar["y"]["field"] == "step"
    assert bar["color"]["scale"]["domain"] == ["Mix effect", "Rate effect", "Total"]
    assert "pp" in bar["x"]["axis"]["labelExpr"] and bar["tooltip"]
    assert has_text_labels(spec)


def test_waterfall_groups_segments_beyond_top_n():
    dec = bundle("explain_change").drivers.dimensions[1]         # gateway: 3 segments
    steps = [r["step"] for r in valid(charts.waterfall(dec, top_n=2))["data"]["values"]]
    assert "Other segments · mix" in steps and "Other segments · rate" in steps and len(steps) == 2 * 3 + 3


@pytest.mark.parametrize("fmt,expect", [("pct", "%"), ("pp", "pp"), ("inr", "₹"), ("int", ",.0f")])
def test_bars_axis_format(fmt, expect):
    rows = [{"method": "UPI", "v": 0.885}, {"method": "CARD", "v": 0.965}]
    spec = valid(charts.bars(rows, "method", "v", fmt))
    assert expect in spec["encoding"]["y"]["axis"]["labelExpr"]
    assert spec["encoding"]["x"]["field"] == "method" and has_text_labels(spec)


def test_bars_with_color_and_dates_are_json_safe():
    from datetime import date
    rows = [{"d": date(2026, 11, 19), "g": g, "v": 3} for g in ("PG_A", "PG_B")]
    spec = valid(charts.bars(rows, "d", "v", "int", color="g"))
    assert spec["encoding"]["xOffset"]["field"] == "g" and spec["data"]["values"][0]["d"] == "2026-11-19"


def test_trend():
    spec = valid(charts.trend([{"day": "2026-11-18", "sr": 0.91}, {"day": "2026-11-19", "sr": 0.92}], "day", "sr", "pct"))
    assert spec["encoding"]["x"]["type"] == "temporal" and spec["mark"]["type"] == "line"
    spec = valid(charts.trend([{"hour": h, "n": h, "gw": "PG_C"} for h in range(24)], "hour", "n", "int", color="gw"))
    assert spec["encoding"]["x"]["type"] == "ordinal" and spec["encoding"]["strokeDash"]["field"] == "gw"


def test_recon_bridge():
    recon = bundle("reconcile").recon
    spec = valid(charts.recon_bridge(recon))
    rows = spec["data"]["values"]
    assert [r["step"] for r in rows][0] == "Transaction GMV" and rows[-1]["step"] == "Settled net"
    assert rows[-2]["end"] == pytest.approx(recon.settled_net_inr)   # components bridge GMV to net exactly
    assert {r["kind"] for r in rows} >= {"Total", "Reduces payout", "Adds to payout"}
    assert has_text_labels(spec)


def test_fixture_charts_are_valid():
    specs = [e.chart for name in ("explain_change", "sql_route", "reconcile") for e in bundle(name).evidence]
    assert len(specs) == 6 and all(specs)
    for spec in specs:
        valid(spec)

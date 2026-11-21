"""The web UI recolours charts through one map: it must cover every colour sherpa/charts.py emits."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_map_covers_every_chart_colour():
    colours = {c.upper() for c in re.findall(r"#[0-9A-Fa-f]{6}", (ROOT / "sherpa/charts.py").read_text())}
    themes = json.loads((ROOT / "web/lib/chart-colors.json").read_text())
    assert colours, "found no colours in charts.py"
    assert set(themes) == {"light", "dark"}
    assert themes["light"].keys() == themes["dark"].keys()
    assert colours <= themes["light"].keys(), f"not mapped: {sorted(colours - themes['light'].keys())}"

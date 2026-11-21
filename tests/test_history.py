"""History, permalinks and feedback: every read of a run is scoped to the asking persona, in the DB and in fixture mode.
A run of another persona, a missing run and a run saved without its bundle all give the same bare 404."""
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import backend
from app.api import app
from sherpa import runs
from sherpa.config import load_access, settings
from sherpa.contracts import AnswerBundle

client = TestClient(app)
NOT_FOUND = {"detail": "Not Found"}


def feedback(run_id: str, persona: str, rating: int):
    return client.post(f"/api/runs/{run_id}/feedback", json={"persona": persona, "rating": rating})


def admin():
    return psycopg.connect(settings().admin_dsn())


# ------------------------------------------------------------------ fixture mode (no DB)
@pytest.fixture
def fixture_mode(monkeypatch):
    monkeypatch.setenv("SHERPA_UI_FIXTURES", "1")


def test_fixture_history_is_persona_scoped(fixture_mode):
    head = client.get("/api/history?persona=head").json()
    assert [h["run_id"] for h in head] == ["fx-explain-0001", "fx-recon-0001", "fx-sql-0001", "fx-clarify-0001",
                                           "fx-error-0001"]
    assert head[0] == {"run_id": "fx-explain-0001", "question": "Why did success rate drop last week?",
                       "status": "answered", "confidence": "medium", "asked_at": "fixture"}
    assert [h["run_id"] for h in client.get("/api/history?persona=rm_south").json()] == ["fx-refused-0001"]
    assert len(client.get("/api/history?persona=head&limit=2").json()) == 2
    for bad in ("persona=nobody", "persona=head&limit=51", "persona=head&limit=0", ""):
        assert client.get(f"/api/history?{bad}").status_code == 422, bad


def test_fixture_run_and_feedback_are_persona_scoped(fixture_mode):
    r = client.get("/api/runs/fx-explain-0001?persona=head").json()
    assert r["bundle"]["run_id"] == "fx-explain-0001" and r["view"]["claims"] and r["view"]["footprint"]["items"]
    for url in ("/api/runs/fx-explain-0001?persona=rm_south", "/api/runs/fx-refused-0001?persona=head",
                "/api/runs/nope?persona=head"):
        resp = client.get(url)
        assert (resp.status_code, resp.json()) == (404, NOT_FOUND), url
    assert feedback("fx-explain-0001", "head", 1).json() == {"run_id": "fx-explain-0001", "feedback": "up"}
    assert feedback("fx-explain-0001", "head", -1).json() == {"run_id": "fx-explain-0001", "feedback": "down"}
    assert feedback("fx-explain-0001", "rm_south", 1).status_code == 404
    assert feedback("fx-refused-0001", "rm_south", 1).status_code == 200
    assert feedback("fx-explain-0001", "head", 0).status_code == 422


# ------------------------------------------------------------------ the database
def _bundle(persona: str) -> AnswerBundle:
    return backend.load_fixture("explain_change").model_copy(
        update={"run_id": f"test-{uuid.uuid4().hex[:12]}", "persona": persona})


@pytest.fixture
def saved(monkeypatch):
    """One app run per persona, saved through runs.save_run; deleted with its feedback afterwards."""
    monkeypatch.setenv("SHERPA_RUN_SOURCE", "app")
    monkeypatch.delenv("SHERPA_UI_FIXTURES", raising=False)
    monkeypatch.setattr(backend, "pipeline_status", lambda: (object(), None))   # DB mode, and nothing is asked
    bs = {p: _bundle(p) for p in ("head", "rm_south")}
    for b in bs.values():
        runs.save_run(b)
    yield bs
    ids = [b.run_id for b in bs.values()]
    with admin() as conn:
        conn.execute("DELETE FROM app.run_feedback WHERE run_id = ANY(%s)", (ids,))
        conn.execute("DELETE FROM app.runs WHERE run_id = ANY(%s)", (ids,))


@pytest.mark.db
def test_save_run_stores_the_whole_bundle(saved):
    b = saved["head"]
    assert runs.get_run(b.run_id, "head") == b
    assert runs.get_run(b.run_id, "rm_south") is None and runs.get_run("no-such-run", "head") is None


@pytest.mark.db
def test_history_is_persona_scoped(saved):
    for p, other in (("head", "rm_south"), ("rm_south", "head")):
        got = client.get(f"/api/history?persona={p}&limit=50").json()
        ids = [h["run_id"] for h in got]
        assert ids[0] == saved[p].run_id and saved[other].run_id not in ids   # newest first, own persona only
        assert got[0]["question"] == saved[p].question and got[0]["status"] == "answered"
        assert got[0]["confidence"] == "medium" and got[0]["asked_at"][-6:-5] == " "   # '21 Nov 2026 15:30'


@pytest.mark.db
def test_permalink_is_persona_scoped(saved):
    for p, other in (("head", "rm_south"), ("rm_south", "head")):
        r = client.get(f"/api/runs/{saved[p].run_id}?persona={p}")
        assert r.status_code == 200 and r.json()["bundle"]["run_id"] == saved[p].run_id and r.json()["view"]["claims"]
        resp = client.get(f"/api/runs/{saved[p].run_id}?persona={other}")
        assert (resp.status_code, resp.json()) == (404, NOT_FOUND)
    assert client.get("/api/runs/no-such-run?persona=head").json() == NOT_FOUND


@pytest.mark.db
def test_run_without_a_bundle_is_not_reopened(saved):
    rid = f"test-{uuid.uuid4().hex[:12]}"   # a run saved before app.runs had a bundle column
    with admin() as conn:
        conn.execute("INSERT INTO app.runs (run_id, persona, question, status, source) "
                     "VALUES (%s, 'head', 'q', 'answered', 'app')", (rid,))
    try:
        assert client.get(f"/api/runs/{rid}?persona=head").status_code == 404
        assert feedback(rid, "head", 1).status_code == 404
        assert rid not in [h["run_id"] for h in client.get("/api/history?persona=head&limit=50").json()]
    finally:
        with admin() as conn:
            conn.execute("DELETE FROM app.runs WHERE run_id = %s", (rid,))


@pytest.mark.db
def test_feedback_is_persona_scoped_and_the_latest_wins(saved):
    h, s = saved["head"].run_id, saved["rm_south"].run_id
    assert feedback(s, "head", 1).json() == NOT_FOUND and feedback(h, "rm_south", 1).json() == NOT_FOUND
    assert feedback(h, "head", 1).json() == {"run_id": h, "feedback": "up"}
    assert feedback(h, "head", -1).json() == {"run_id": h, "feedback": "down"}   # undo: the other thumb
    assert feedback(s, "rm_south", 1).status_code == 200
    with admin() as conn:   # insert-only: both of head's ratings are kept, the refused ones never landed
        rows = conn.execute("SELECT run_id, persona, rating FROM app.run_feedback WHERE run_id = ANY(%s) ORDER BY at",
                            ([h, s],)).fetchall()
    assert rows == [(h, "head", 1), (h, "head", -1), (s, "rm_south", 1)]
    r = client.get("/api/runs").json()
    recent = {x["run_id"]: x for x in r["recent"]}
    assert recent[h]["feedback"] == "down" and recent[s]["feedback"] == "up"
    assert 0 < runs.run_stats()["helpful_rate"] < 1   # one up, one down among the latest ratings
    assert next(t for t in r["tiles"] if t["label"] == "Helpful")["value"].endswith("%")


@pytest.mark.db
def test_app_role_cannot_update_or_delete_runs_or_feedback():
    role = load_access().app_role
    with admin() as conn:
        for table in ("app.runs", "app.run_feedback"):
            for priv, want in (("INSERT", True), ("SELECT", True), ("UPDATE", False), ("DELETE", False),
                               ("TRUNCATE", False)):
                got = conn.execute("SELECT has_table_privilege(%s, %s, %s)", (role, table, priv)).fetchone()[0]
                assert got is want, (table, priv)

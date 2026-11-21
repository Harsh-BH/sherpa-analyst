"""Seeded-database checks: access control matches access.yaml, the ground truth reproduces, the data is
calibrated and deterministic. Reads `sherpa`; writes only the scratch database `sherpa_test`."""
import os
import dataclasses
import json
import subprocess
import sys
from datetime import timedelta

import psycopg
import pytest
from psycopg import sql

from db import roles
from gen.generate import SCHEMA_SQL, build, create_database, verify
from sherpa.config import ROOT, load_access, load_catalog, settings

pytestmark = pytest.mark.db
ACCESS = load_access()
PERSONAS = list(ACCESS.personas.values())
REGION_TABLES = [t for t, cols in ACCESS.exposed_tables.items() if "region" in cols]
SCRATCH = f"sherpa_test_{os.getpid()}"   # per process: concurrent test runs (several worktrees) must not drop each other's scratch DB


def admin(db=None):
    s = settings()
    return psycopg.connect(dataclasses.replace(s, db_name=db or s.db_name).admin_dsn())


def as_role(role):
    return psycopg.connect(settings().dsn(role), autocommit=True)


def test_one_data_version_row():
    with admin() as c:
        assert c.execute("SELECT count(*) FROM analytics.data_version").fetchone()[0] == 1


# ---------------------------------------------------------------- access control (db/roles.py)
def test_column_grants_equal_access_yaml():
    want = {(t, col) for t, cols in ACCESS.exposed_tables.items() for col in cols}
    with admin() as c:
        for p in PERSONAS:
            rows = c.execute("SELECT table_schema, table_name, column_name, privilege_type "
                             "FROM information_schema.column_privileges WHERE grantee = %s", (p.db_role,)).fetchall()
            assert {(t, col) for _, t, col, _ in rows} == want, p.name
            assert {(s, priv) for s, _, _, priv in rows} == {("analytics", "SELECT")}, p.name
            assert c.execute("SELECT count(*) FROM information_schema.table_privileges WHERE grantee = %s",
                             (p.db_role,)).fetchone()[0] == 0, f"{p.name} has a table-level grant"
        app = c.execute("SELECT table_schema, table_name, privilege_type FROM information_schema.table_privileges "
                        "WHERE grantee = %s", (ACCESS.app_role,)).fetchall()
        assert set(app) == {("app", "runs", "INSERT"), ("app", "runs", "SELECT"),
                            ("app", "run_feedback", "INSERT"), ("app", "run_feedback", "SELECT")}
        assert c.execute("SELECT count(*) FROM information_schema.column_privileges WHERE grantee = 'PUBLIC' "
                         "AND table_schema IN ('raw', 'analytics', 'app')").fetchone()[0] == 0


def test_every_region_table_forces_rls():
    with admin() as c:
        rows = c.execute(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM information_schema.columns ic "
            "JOIN pg_namespace n ON n.nspname = ic.table_schema "
            "JOIN pg_class c ON c.relnamespace = n.oid AND c.relname = ic.table_name "
            "WHERE ic.table_schema = 'analytics' AND ic.column_name = 'region'").fetchall()
    assert {r[0] for r in rows} == set(REGION_TABLES)
    assert all(r[1] and r[2] for r in rows), rows


@pytest.mark.parametrize("persona", PERSONAS, ids=lambda p: p.name)
def test_persona_sees_only_its_regions(persona):
    with as_role(persona.db_role) as c:
        for t in REGION_TABLES:
            got = {r[0] for r in c.execute(f"SELECT DISTINCT region FROM analytics.{t}")}
            assert got == set(persona.regions), (persona.name, t, got)


@pytest.mark.parametrize("persona", PERSONAS, ids=lambda p: p.name)
def test_persona_cannot_read_raw_or_app_or_write(persona):
    with as_role(persona.db_role) as c:
        assert c.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
        assert c.execute("SHOW statement_timeout").fetchone()[0] == "5s"
        assert c.execute("SHOW search_path").fetchone()[0] == "analytics"
        for q in ("SELECT count(*) FROM raw.transaction_events", "SELECT count(*) FROM raw.merchants",
                  "SELECT count(*) FROM app.runs"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(q)
        c.execute("BEGIN READ WRITE")   # even with the read-only default switched off, grants refuse writes
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("INSERT INTO analytics.banks (bank_id, name, bank_type) VALUES ('X', 'X', 'X')")
        c.execute("ROLLBACK")


def test_values_equal_the_catalog_vocabularies():
    with admin() as c:
        for d in load_catalog().dimensions:
            if d.values and "transactions" in d.tables:
                got = {str(r[0]) for r in c.execute(f"SELECT DISTINCT {d.column} FROM analytics.transactions "
                                                    f"WHERE {d.column} IS NOT NULL")}
                assert got == set(d.values), d.name


# ---------------------------------------------------------------- ground truth and calibration
@pytest.fixture(scope="module")
def truth():
    with admin() as c:
        seed, start, as_of = c.execute("SELECT seed, data_start, as_of FROM analytics.data_version").fetchone()
    _, t = build(seed, (as_of - start).days + 1)
    path = ROOT / "data" / f"ground_truth_{seed}.json"
    if path.exists():
        assert json.loads(path.read_text()) == json.loads(json.dumps(t)), f"{path} is stale: re-run make seed"
    return t


def test_ground_truth_reproduces_against_the_db(truth):
    with admin() as c, c.cursor() as cur:
        assert verify(cur, truth) == []
    ids = {s["id"] for s in truth["scenarios"]}
    assert ids == {"S1", "S2", "S3", "S4", "S5a", "S5b", "S6"}
    s1 = next(s for s in truth["scenarios"] if s["id"] == "S1")
    assert s1["expected"]["simpson"] and s1["expected"]["direction"] == "down"
    assert 0.43 <= s1["facts"]["upi_share_baseline"] <= 0.47 and 0.55 <= s1["facts"]["upi_share_current"] <= 0.61


def test_verify_catches_a_wrong_truth(truth):
    bad = json.loads(json.dumps(truth))
    s4 = next(s for s in bad["scenarios"] if s["id"] == "S4")
    s4["expected"]["refunds"] += 1.0
    with admin() as c, c.cursor() as cur:
        assert any(m.startswith("S4 refunds") for m in verify(cur, bad))


def test_calibration_in_a_quiet_week(truth):
    from datetime import date
    planted = {date.fromisoformat(s[k]["start"]) for s in truth["scenarios"] if s["id"] in ("S2", "S3")
               for k in ("window", "baseline")}
    start = date.fromisoformat(truth["data_start"])
    while any(start <= d <= start + timedelta(days=6) for d in planted):
        start += timedelta(days=1)
    assert start + timedelta(days=6) < date(2026, 11, 13), "no quiet week before S1"
    with admin() as c:
        rates = dict(c.execute(
            "SELECT payment_method, avg((status = 'SUCCESS')::int) FROM analytics.transactions "
            "WHERE status <> 'DROPPED' AND txn_date BETWEEN %s AND %s GROUP BY 1",
            (start, start + timedelta(days=6))).fetchall())
    assert abs(float(rates["UPI"]) - 0.885) <= 0.015, rates
    assert abs(float(rates["CARD"]) - 0.96) <= 0.015, rates


# ---------------------------------------------------------------- determinism (scratch database)
def _table_hashes(db):
    tables = ["raw.banks", "raw.merchants", "raw.transaction_events", "raw.settlements", "analytics.banks",
              "analytics.merchants", "analytics.transactions", "analytics.settlements", "analytics.dq_daily"]
    with admin(db) as c:
        out = {t: c.execute(f"SELECT md5(string_agg(t::text, E'\\n' ORDER BY t::text)) FROM {t} t").fetchone()[0]
               for t in tables}
        out["data_version"] = c.execute("SELECT version, seed, data_start, as_of, row_count "
                                        "FROM analytics.data_version").fetchall()
    return out


@pytest.fixture
def scratch():
    """Empty scratch database with the schema; dropped afterwards. Never `sherpa`."""
    create_database(SCRATCH)
    with admin(SCRATCH) as c:
        c.execute(SCHEMA_SQL.read_text())
    yield SCRATCH
    with admin("postgres") as c:
        c.autocommit = True
        c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(SCRATCH)))


def test_same_seed_gives_identical_rows(tmp_path, scratch):
    hashes = []
    for i in range(2):   # separate processes: hash randomisation must not leak into the data
        subprocess.run([sys.executable, "-m", "gen.generate", "--seed", "42", "--days", "3", "--db", scratch,
                        "--truth", str(tmp_path / f"truth{i}.json")], check=True, cwd=ROOT, capture_output=True)
        hashes.append(_table_hashes(scratch))
    assert hashes[0] == hashes[1]
    assert all(hashes[0].values())
    assert (tmp_path / "truth0.json").read_bytes() == (tmp_path / "truth1.json").read_bytes()


# ---------------------------------------------------------------- adversarial review regressions (db/roles.py)
ALL_ROLES = [p.db_role for p in PERSONAS] + [ACCESS.app_role]


@pytest.mark.parametrize("role", ALL_ROLES)
def test_r1_r8_dangerous_functions_are_revoked(role):
    with admin() as c:
        allowed = [f for f in roles.REVOKED_FUNCTIONS
                   if c.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, f"pg_catalog.{f}")).fetchone()[0]]
    assert allowed == []
    with as_role(role) as c:
        c.execute("BEGIN READ WRITE")
        for q in ("SELECT ('SELECT rolname::text FROM pg_roles').ts_stat",    # field-selection form from R1
                  "SELECT (pg_backend_pid()).pg_cancel_backend",
                  "SELECT ('server_version').current_setting",
                  "SELECT lo_from_bytea(0, '\\x00'::bytea)"):                # R8: persistent write
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(q)
            c.execute("ROLLBACK")
            c.execute("BEGIN READ WRITE")
        c.execute("ROLLBACK")


@pytest.mark.parametrize("role", ALL_ROLES)
def test_r10_roles_connect_only_to_their_database(role):
    db = settings().db_name
    with admin() as c:
        priv = lambda d, p: c.execute("SELECT has_database_privilege(%s, %s, %s)", (role, d, p)).fetchone()[0]  # noqa: E731
        assert [(d, p) for d in ("postgres", "template1", db) for p in ("CONNECT", "TEMP") if priv(d, p)] == [(db, "CONNECT")]
    s = settings()
    with pytest.raises(psycopg.OperationalError, match="permission denied"):
        psycopg.connect(dataclasses.replace(s, db_name="postgres").dsn(role), connect_timeout=3).close()


def test_r9_reapplying_roles_wipes_settings_a_role_gave_itself(scratch):
    roles.apply(scratch)
    with admin(scratch) as c:   # what a persona or the app could do to itself with its own login
        c.execute(f"ALTER ROLE sherpa_rm_south IN DATABASE {scratch} SET row_security = off")
        c.execute(f"ALTER ROLE sherpa_rm_south IN DATABASE {scratch} SET default_transaction_read_only = off")
        c.execute("ALTER ROLE sherpa_app SET work_mem = '8MB'")   # global; harmless if the test dies here
    roles.apply(scratch)
    with admin(scratch) as c:
        rows = c.execute("SELECT r.rolname, s.setdatabase <> 0, s.setconfig FROM pg_db_role_setting s "
                         "JOIN pg_roles r ON r.oid = s.setrole WHERE r.rolname = ANY(%s)", (ALL_ROLES,)).fetchall()
    want = sorted(f"{k}={v.strip(chr(39))}" for k, v in roles.PERSONA_SETTINGS.items())
    assert sorted((r, per_db, sorted(cfg)) for r, per_db, cfg in rows) == sorted(
        (p.db_role, False, want) for p in PERSONAS)


def test_r12_a_role_dropped_from_access_yaml_loses_login_and_grants(scratch):
    stale = "sherpa_zz_stale"
    with admin(scratch) as c:
        c.execute(f"DROP ROLE IF EXISTS {stale}")
        c.execute(f"CREATE ROLE {stale} LOGIN")
        c.execute(f"GRANT CONNECT ON DATABASE {scratch} TO {stale}")
        c.execute(f"GRANT USAGE ON SCHEMA analytics TO {stale}")
        c.execute(f"GRANT SELECT ON analytics.data_version TO {stale}")
    try:
        roles.apply(scratch)
        with admin(scratch) as c:
            login, table, conn = c.execute(
                "SELECT rolcanlogin, has_table_privilege(%s, 'analytics.data_version', 'SELECT'), "
                "has_database_privilege(%s, %s, 'CONNECT') FROM pg_roles WHERE rolname = %s",
                (stale, stale, scratch, stale)).fetchone()
        assert (login, table, conn) == (False, False, False)
    finally:
        with admin(scratch) as c:
            c.execute(f"DROP OWNED BY {stale}")
            c.execute(f"DROP ROLE {stale}")

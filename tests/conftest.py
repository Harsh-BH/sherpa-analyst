"""Shared test setup. Tests marked `db` are skipped when the seeded Postgres is not reachable."""
import os

os.environ["SHERPA_RUN_SOURCE"] = "test"   # first: every run pytest saves (TestClient -> API -> pipeline too) is a test run

from functools import lru_cache  # noqa: E402

import pytest  # noqa: E402


@lru_cache(maxsize=1)
def db_ready() -> bool:
    try:
        import psycopg

        from sherpa.config import settings

        with psycopg.connect(settings().admin_dsn(), connect_timeout=2) as conn:
            return conn.execute("SELECT count(*) FROM analytics.data_version").fetchone()[0] > 0
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    db_items = [i for i in items if "db" in i.keywords]
    if db_items and not db_ready():
        skip = pytest.mark.skip(reason="seeded Postgres not reachable (docker compose up -d db && make seed)")
        for item in db_items:
            item.add_marker(skip)

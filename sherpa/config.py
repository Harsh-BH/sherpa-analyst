"""Settings from the environment (.env), loaders for the catalog and access files, analysis thresholds.

Owner: master.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from .contracts import Access, Catalog, Persona

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "sherpa" / "catalog.yaml"
ACCESS_PATH = ROOT / "db" / "access.yaml"

# ---- analysis thresholds (docs/ARCHITECTURE.md "Driver engine"); constants, not env knobs
MIN_SUPPORT = 1000            # a segment needs >= this denominator in BOTH periods to be reported alone
MIN_SHARE = 0.01              # ... and >= 1% of volume in at least one period
MIN_RATE_DELTA = 0.003        # 0.3 pp: smallest rate change worth calling material
MIN_CONTRIBUTION = 0.05       # a segment must carry >= 5% of |delta| to be material
FDR_Q = 0.05                  # Benjamini-Hochberg level
SIMPSON_MIX_SHARE = 0.5       # mix must explain >= 50% of |delta| for the Simpson flag
AMBIGUITY_THRESHOLD = 0.003   # ask the user only if readings differ by more than 0.3 pp
STATEMENT_TIMEOUT_MS = 5000
MAX_ROWS = 5000


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader (KEY=VALUE, # comments). Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    admin_password: str
    role_password: str
    llm_backend: str          # auto | anthropic | claude-cli | none
    anthropic_api_key: str
    planner_model: str
    narrator_model: str

    def dsn(self, user: str, password: str | None = None) -> str:
        pw = self.role_password if password is None else password
        return f"host={self.db_host} port={self.db_port} dbname={self.db_name} user={user} password={pw}"

    def admin_dsn(self) -> str:
        return self.dsn("postgres", self.admin_password)


@lru_cache(maxsize=1)
def settings() -> Settings:
    _load_dotenv()
    e = os.environ.get
    return Settings(
        db_host=e("SHERPA_DB_HOST", "localhost"),
        db_port=int(e("SHERPA_DB_PORT", "5433")),
        db_name=e("SHERPA_DB_NAME", "sherpa"),
        admin_password=e("POSTGRES_PASSWORD", ""),
        role_password=e("SHERPA_ROLE_PASSWORD", ""),
        llm_backend=e("SHERPA_LLM_BACKEND", "auto"),
        anthropic_api_key=e("ANTHROPIC_API_KEY", ""),
        planner_model=e("SHERPA_PLANNER_MODEL", "claude-opus-5-5"),
        narrator_model=e("SHERPA_NARRATOR_MODEL", "claude-sonnet-5-5"),
    )


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    return Catalog.model_validate(yaml.safe_load(CATALOG_PATH.read_text()))


@lru_cache(maxsize=1)
def load_access() -> Access:
    raw = yaml.safe_load(ACCESS_PATH.read_text())
    raw["personas"] = {k: {"name": k, **v} for k, v in raw["personas"].items()}
    return Access.model_validate(raw)


def persona(name: str) -> Persona:
    return load_access().persona(name)


if __name__ == "__main__":
    cat, acc = load_catalog(), load_access()
    names = {m.name for m in cat.metrics}
    dims = {d.name for d in cat.dimensions}
    for m in cat.metrics:
        assert m.table in cat.tables, m.name
        assert (m.type == "ratio") == (m.numerator is not None and m.denominator is not None), m.name
        assert (m.type == "simple") == (m.measure is not None), m.name
        assert set(m.variants) <= names, m.name
    for d in cat.dimensions:
        assert set(d.tables) <= set(cat.tables), d.name
        for t in d.tables:
            assert d.column in acc.exposed_tables[cat.tables[t].sql_table.split(".")[1]], (d.name, t)
    for vq in cat.verified_queries:
        p = vq.plan
        assert p.get("metric") in names, vq.name
        assert set(p.get("dimensions", [])) <= dims, vq.name
    print(f"config ok: {len(cat.metrics)} metrics, {len(cat.dimensions)} dimensions, "
          f"{len(cat.verified_queries)} verified queries, personas={list(acc.personas)}")

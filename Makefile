# Sherpa. `make seed` = generate -> build analytics (same transaction) -> roles; idempotent, re-run any time.
SEED ?= 42
DB ?= sherpa

.PHONY: up seed seed-eval test app eval down

up:
	docker compose up -d db

seed:
	uv run python -m gen.generate --seed $(SEED) --db $(DB)
	uv run python -m db.roles --db $(DB)

# second seed for the eval, in its own database (created and schema'd if missing)
seed-eval:
	uv run python -m gen.generate --seed 7 --db sherpa_s7 --create
	uv run python -m db.roles --db sherpa_s7

test:
	uv run pytest

app:
	uv run streamlit run app/streamlit_app.py

eval:
	@if [ -f eval/run.py ]; then uv run python -m eval.run; else echo "eval/run.py not there yet"; fi

# never -v: the volume holds the seeded data
down:
	docker compose down

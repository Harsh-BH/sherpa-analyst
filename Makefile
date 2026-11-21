# Sherpa. `make seed` = generate -> build analytics (same transaction) -> roles; idempotent, re-run any time.
SEED ?= 42
DB ?= sherpa

.PHONY: up seed seed-eval test app api web types e2e eval down

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

API = uv run uvicorn app.api:app --host 127.0.0.1 --port 8000 --reload

api:
	$(API)

web:
	pnpm -C web dev

# api + web on 127.0.0.1:3000; the API is stopped when the web server exits
app:
	@$(API) & api=$$!; trap 'kill $$api 2>/dev/null' EXIT; pnpm -C web dev

# regenerate web/lib/api-types.ts; needs `make api` running
types:
	pnpm -C web types

# browser tests in fixture mode (starts its own servers on 8765 and 3765)
e2e:
	pnpm -C web e2e

eval:
	@if [ -f eval/run.py ]; then uv run python -m eval.run; else echo "eval/run.py not there yet"; fi

# never -v: the volume holds the seeded data
down:
	docker compose down

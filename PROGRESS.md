# Progress

Build order follows `finance-tracker-spec.md` section 6. One phase per commit.

## Decisions (apply to all phases)

- Money is `Decimal` with two places, never float. Rendered as a JSON string (`"12.40"`) so clients never touch binary floats.
- Schema changes between phases use `SQLModel.metadata.create_all` only. When a phase changes the schema, recreate the volume (`docker compose down -v`). No Alembic.
- "Today" for summaries comes from the client's timezone, sent with the request. No server-side default timezone.
- Categories are per user: a seeded default set plus the user's own custom ones.

## Phase 1 — Core skeleton

**Status:** done, verified by owner

**Delivered:** FastAPI app, `GET /health`, `Expense` model (Decimal price, date, optional description, status enum), `POST /expenses`, `GET /expenses`, `GET /expenses/{id}` backed by an in-memory store injected via `Depends`.

**Verified:** every endpoint hit with curl; 201 on create, 200 on reads, 404 on unknown id, 422 on negative price, more than two decimal places, non-integer id. Client-supplied `status` is ignored (always `confirmed`).

**Known gaps:** data lives in process memory and is lost on restart (by design, phase 2 fixes). No PATCH/DELETE/filters until phase 4. No categories until phase 3.

## Phase 2 — Persistence

**Status:** done, awaiting owner verification

**Delivered:** `docker-compose.yml` with `postgres:16-alpine` on a named volume `pgdata` and a `pg_isready` healthcheck. `app/config.py` (pydantic-settings, reads `DATABASE_URL` from env / `.env`). `app/database.py` with one engine, `get_session` dependency, `wait_for_db()` (probes `SELECT 1` with exponential backoff, 0.5s to 5s, up to `DB_STARTUP_TIMEOUT_SECONDS`, default 30) and `create_tables()`. Both run in the FastAPI lifespan. `Expense` is now a table: `NUMERIC(10,2)` price, Postgres enum `expense_status` storing the lowercase values. `app/store.py` removed; routers take a `Session`.

**Verified (against a real Postgres 16, same `DATABASE_URL`):** table schema inspected with `\d expenses`; POST/GET/GET-by-id/404 as in phase 1; rows visible in psql; data present after killing and restarting the app. Started the app with Postgres stopped: four backoff retries logged, then startup completed when Postgres came up. With a 3s budget and Postgres down: startup fails with `RuntimeError: Database not reachable after 3s`, exit code 3. `docker compose config` validates.

**Known gaps:** compose path (image pull, volume survival across `down`/`up`) not exercised in the build sandbox because Docker Hub pulls are blocked there; owner verifies locally. Schema is created with `create_all`, no migrations (see Decisions).

## Phase 3 — Categories

**Status:** not started

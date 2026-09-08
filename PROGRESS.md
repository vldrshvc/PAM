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

**Status:** done, verified by owner

**Delivered:** `docker-compose.yml` with `postgres:16-alpine` on a named volume `pgdata` and a `pg_isready` healthcheck. `app/config.py` (pydantic-settings, reads `DATABASE_URL` from env / `.env`). `app/database.py` with one engine, `get_session` dependency, `wait_for_db()` (probes `SELECT 1` with exponential backoff, 0.5s to 5s, up to `DB_STARTUP_TIMEOUT_SECONDS`, default 30) and `create_tables()`. Both run in the FastAPI lifespan. `Expense` is now a table: `NUMERIC(10,2)` price, Postgres enum `expense_status` storing the lowercase values. `app/store.py` removed; routers take a `Session`.

**Verified (against a real Postgres 16, same `DATABASE_URL`):** table schema inspected with `\d expenses`; POST/GET/GET-by-id/404 as in phase 1; rows visible in psql; data present after killing and restarting the app. Started the app with Postgres stopped: four backoff retries logged, then startup completed when Postgres came up. With a 3s budget and Postgres down: startup fails with `RuntimeError: Database not reachable after 3s`, exit code 3. `docker compose config` validates.

**Known gaps:** compose path (image pull, volume survival across `down`/`up`) not exercised in the build sandbox because Docker Hub pulls are blocked there; owner verifies locally. Schema is created with `create_all`, no migrations (see Decisions).

## Phase 3 — Categories

**Status:** done, verified by owner

**Delivered:** `Category` table (`name` unique + indexed, `monthly_limit` nullable `NUMERIC(10,2)`), `expenses.category_id` NOT NULL FK with index. `app/services/categories.py` holds the reserved name `uncategorized`, the default list, an idempotent `seed_default_categories()` run in the lifespan, and a case-insensitive name lookup. `GET /categories`, `POST /categories` (409 on duplicate, case-insensitive), `DELETE /categories/{id}` (reassigns that category's expenses to `uncategorized` in the same transaction, 409 for `uncategorized`, 404 unknown). `POST /expenses` accepts optional `category_id`; omitted falls back to `uncategorized`, unknown id is 422. `ExpenseRead` now carries `category_id`.

**Verified:** schema via psql (unique index on name, FK + index on category_id); seeded 8 categories; create with limit renders `"40.00"`; `"  coffee "` after `Coffee` is 409; blank name and negative limit are 422; expense without category lands on id 1; expense with unknown category is 422; deleting a category with an expense returns 204 and the expense now points at `uncategorized`; deleting `uncategorized` is 409; restart re-seeds nothing (still 8).

**Known gaps:** no way to change `monthly_limit` after creation yet (arrives with budgets in phase 4). No filters on `GET /expenses` (phase 4). Schema changed: existing volumes need `docker compose down -v`.

## Phase 4 — Budget & summaries

**Status:** done, awaiting owner verification

**Delivered:** `PATCH /expenses/{id}` (partial, `exclude_unset`; price/date cannot be nulled; category validated), `DELETE /expenses/{id}`, `GET /expenses?date_from&date_to&category_id` (422 on reversed range, newest first). `PATCH /categories/{id}` for `monthly_limit` (null removes it) and `name` (409 on clash or on renaming `uncategorized`). `app/services/budget.py`: pure budget maths (`category_budget`, `budget_totals`, `month_bounds`, `today_in`) with the rule that only budgeted categories count against `budget_total`/`remaining_total`. `GET /summary/daily?tz=` (widget contract, documented in README) and `GET /summary/monthly?month=YYYY-MM&tz=`. Spending is aggregated with one `GROUP BY category_id` over confirmed expenses in the period. `tz` comes from the client; UTC only if omitted.

**Verified:** limits set and cleared via PATCH; rename, clash (409), rename of `uncategorized` (409), unknown id (404). Filters by date range and category; reversed range 422. Daily summary in Europe/Dublin: spent_today 96.40, month 296.40, budget 400.00, remaining 119.50, Eating out at 115/100 flagged over with remaining -15.00, unbudgeted categories omitted. Monthly lists all 8 categories; `month=2026-08` isolates last month's 999.00 and flags over. Bad tz 422, bad month 422. Expense PATCH of price+category, description→null, price→null 422, bad category 422, empty body no-op. DELETE 204 then 404. Summary recomputed correctly after edits. Log clean.

**Known gaps:** none within scope. All data still global (per-user scoping is phase 6).

## Phase 5 — LLM categorization

**Status:** not started

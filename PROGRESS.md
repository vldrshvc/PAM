# Progress

Build order follows `finance-tracker-spec.md` section 6. One phase per commit.

## Decisions (apply to all phases)

- Money is `Decimal` with two places, never float. Rendered as a JSON string (`"12.40"`) so clients never touch binary floats.
- Schema changes are Alembic migrations applied at startup (since phase 13a). Before that, `create_all` plus volume recreation.
- "Today" for summaries comes from the client's timezone, sent with the request. No server-side default timezone.
- Categories are per user: a seeded default set plus the user's own custom ones.
- LLM provider is a config choice, not a code choice. The categorizer talks to any OpenAI-compatible chat endpoint via the `openai` client; Google Gemini's free tier (Flash) is the default after Groq signup failed for the owner. Groq, OpenRouter or Anthropic work by changing `LLM_BASE_URL`/`LLM_MODEL`. Owner's decision, replacing the spec's Anthropic-only wording.

## Definition of done (spec §8)

- [x] Runs from a clean clone with `docker compose up`
- [x] Data persists across restarts (named volume; `pool_pre_ping` for reconnects)
- [x] Core + category + budget + summary + categorization + auth endpoints
- [x] pytest suite green (76 tests, real Postgres, LLM faked)
- [x] Deployed to a public URL: https://pam-u8qh.onrender.com
- [x] README with stack, setup, example requests
- [x] Screenshots in README (mobile app, headless Chromium renders)

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

**Status:** done, verified by owner

**Delivered:** `PATCH /expenses/{id}` (partial, `exclude_unset`; price/date cannot be nulled; category validated), `DELETE /expenses/{id}`, `GET /expenses?date_from&date_to&category_id` (422 on reversed range, newest first). `PATCH /categories/{id}` for `monthly_limit` (null removes it) and `name` (409 on clash or on renaming `uncategorized`). `app/services/budget.py`: pure budget maths (`category_budget`, `budget_totals`, `month_bounds`, `today_in`) with the rule that only budgeted categories count against `budget_total`/`remaining_total`. `GET /summary/daily?tz=` (widget contract, documented in README) and `GET /summary/monthly?month=YYYY-MM&tz=`. Spending is aggregated with one `GROUP BY category_id` over confirmed expenses in the period. `tz` comes from the client; UTC only if omitted.

**Verified:** limits set and cleared via PATCH; rename, clash (409), rename of `uncategorized` (409), unknown id (404). Filters by date range and category; reversed range 422. Daily summary in Europe/Dublin: spent_today 96.40, month 296.40, budget 400.00, remaining 119.50, Eating out at 115/100 flagged over with remaining -15.00, unbudgeted categories omitted. Monthly lists all 8 categories; `month=2026-08` isolates last month's 999.00 and flags over. Bad tz 422, bad month 422. Expense PATCH of price+category, description→null, price→null 422, bad category 422, empty body no-op. DELETE 204 then 404. Summary recomputed correctly after edits. Log clean.

**Known gaps:** none within scope. All data still global (per-user scoping is phase 6).

## Phase 5 — LLM categorization

**Status:** done, verified by owner

**Delivered:** `app/llm.py` wraps one OpenAI-compatible chat call (`temperature=0`, `max_tokens=30`, one retry, configurable timeout) and translates SDK exceptions into `LLMUnavailableError`; a missing key raises `LLMNotConfiguredError`. `app/services/categorization.py` is pure logic: constrained system prompt, user prompt listing the live category names, `parse_amount()` (currency-adjacent number wins over a bare one, comma decimal accepted), `match_category()` (exact case-insensitive after stripping quotes/periods, no fuzzy matching), and `categorize()` which falls back to `uncategorized` whenever the answer does not match. `POST /categorize` returns `{category, amount, fell_back}`; it never writes anything. Errors: 503 when `LLM_API_KEY` is unset, 502 when the provider fails or times out, 422 on blank text. Config: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`.

**Verified:** amount parser and matcher checked on 18 hand cases. Endpoint exercised against a local stand-in that implements the OpenAI chat-completions protocol (Groq is unreachable from the sandbox): valid answer → Groceries with amount 12.40; invented category "Pizza Palace" → fallback; sloppy `"Eating out".` → matched after fix; empty answer → fallback; provider 500 → 502; provider hang → 502 timeout after 2s; no key → 503; blank text → 422; GET /categorize → 405. Stand-in confirmed the request carries the configured model, temperature 0, max_tokens 30 and a Bearer key.

**Known gaps:** not yet run against real Groq; owner to verify with a real key. Categorization is stateless: the client still has to POST /expenses with the returned category_id.

## Phase 6 — Auth

**Status:** done, verified by owner

**Delivered:** `users` table (unique username, argon2id hash). `app/security.py`: `hash_password`/`verify_password` (argon2-cffi), `create_access_token` (PyJWT HS256, `sub`=user id, `iat`, `exp`), `get_current_user` dependency (401 + `WWW-Authenticate: Bearer` for missing, malformed, wrong-signature or expired tokens, or a deleted user). `POST /register` (201; 409 on case-insensitive duplicate; username charset validated; password 8–128) seeds the user's default categories in the same transaction via `flush()`. `POST /token` is the OAuth2 password form; one error message for unknown user and wrong password. `categories` gained `user_id` and the unique constraint is now `(user_id, name)`; `expenses` gained `user_id`. Every expense, category, summary and categorize route requires a token and filters by `user.id`; another user's row is 404 (or 422 when referenced in a body), never 403, so existence is not leaked. Config: `JWT_SECRET` (min 32 chars, app refuses to start otherwise), `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` (default 30 days, since the widget has no refresh flow). Startup seeding removed.

**Verified:** schema via psql (argon2id hashes stored, `$argon2id$v=19$m=65536,t=3,p=4`; unique `(user_id, name)`; FKs). Register: 201, duplicate `Vlad` 409, short password 422, `bob smith` 422. Token: wrong password 401, unknown user 401 with identical message. Protected routes: no token 401 with `WWW-Authenticate`, garbage 401, expired 401, wrong-secret 401. Two users each get 8 seeded categories with distinct ids. Cross-user: creating an expense in another user's category 422; GET/PATCH/DELETE another user's expense 404; DELETE another user's category 404; both users can own a "Coffee". Summaries and `/categorize` return only the caller's data. `/health` remains public. Weak `JWT_SECRET` fails at import with a clear validation error. App log contains no passwords.

**Known gaps:** no token refresh or revocation (out of spec). Schema changed: `docker compose down -v` required.

## Phase 7 — Tests

**Status:** done, verified by owner

**Delivered:** `tests/` with 76 tests, `pytest.ini`, `requirements-dev.txt`. `conftest.py` derives a test database from `DATABASE_URL` (`<name>_test`, or `TEST_DATABASE_URL`), creates it if missing, builds the schema once per session, truncates every table after each test, and overrides the `get_session` and `llm_dependency` FastAPI dependencies. `TestClient` is used without the lifespan so the main database is never touched. `FakeLLM` scripts the model's answer or raises like the real client. Coverage by file: budget maths (pure, 9), categorization (pure parsing/matching/fallback plus the endpoint with the fake, 28), auth (12), expenses (11), categories (9), summaries (7).

**Verified:** full suite green in ~11s against a real Postgres 16. Main `finance` database untouched after a run (row counts unchanged), `finance_test` created automatically and emptied at session end. Three deliberate mutations each failed the expected test: counting unbudgeted spend against the budget, fuzzy-matching an invented category, and removing the user check on expense lookup.

**Known gaps:** no CI config (out of scope unless asked). One DeprecationWarning from Starlette's own TestClient, not from app code.

## Phase 8 — Packaging & deploy

**Status:** done, verified by owner. Deployed to Render (free) + Neon (free Postgres) at https://pam-u8qh.onrender.com; `/health` and `POST /register` confirmed on the public URL. Koyeb was closed to new users after the Mistral acquisition.

**Delivered:** `Dockerfile` (python:3.12-slim, dependency layer first, non-root user, `PORT` env with 8000 default), `.dockerignore`, `api` service in compose (builds the image, waits for `db` healthy, `DATABASE_URL` built from the `POSTGRES_*` vars so it points at `db` inside the network, healthcheck on `/health`). `Settings` normalizes `postgres://` / `postgresql://` to the psycopg2 dialect so a hosted connection string works unchanged. README rewritten for a hiring manager: stack, one-command run, example requests, API table, architecture with the decisions that matter, widget contract, tests, configuration, Render + Neon deploy steps, v2 roadmap.

**Verified:** `docker compose config` valid with both services and the composed `DATABASE_URL`; URL normalization checked for `postgres://...?sslmode=require` and pass-through; the container's exact start command run outside Docker with `PORT=8123` serves `/health`; test suite green. Image build and `docker compose up --build` NOT run in the build sandbox (registry blob downloads blocked); owner verifies.

**Known gaps:** no CI config (out of scope).

## Phase 11a — Mobile web app

**Status:** done, verified by owner on the phone

**Delivered:** `app/static/` (index.html, app.js, styles.css, manifest.json, icon.svg) mounted at `/app`; `/` redirects there. Vanilla JS, no build step. Screens: login/register; Today (spent today / this month / remaining, quick-add with `POST /categorize` suggestion prefilling amount, category and description, today's list with delete); Month (spend vs limit per category with progress bars); Categories (add with limit, tap to set/clear limit, delete except `uncategorized`). JWT in `localStorage`; device timezone from `Intl` sent as `tz`. A 401 on any call logs the user out. Installable as a PWA (`display: standalone`). Two static tests added (78 total).

**Verified:** driven end to end in headless Chromium at a 412×915 mobile viewport against the running API and the LLM stand-in: register → suggestion fills 12.40 / Groceries / "SuperValu" → add → list and totals update → fallback suggestion flagged and left as uncategorized → category add with limit, limit edit via prompt, delete → month view totals and bars → expense delete recomputes totals → reload keeps session → logout, wrong password shows the API's message. No console errors. Screenshots in `docs/`.

**Known gaps:** no service worker, so no offline mode (the app needs the API anyway). Limit editing uses a browser `prompt()`; fine on mobile, not pretty.

## Phase 11b — Android home-screen widget

**Status:** not started. Native widget-only project (Kotlin + Glance) polling `GET /summary/daily`.

## Phase 12 — Income & balance

**Status:** done, verified by owner on Render

**Delivered:** `incomes` table (amount, date, `source` enum work/friend/debt/bonus/other, description, user_id) and `users.opening_balance` (NUMERIC(12,2), may be negative). `app/services/ledger.py`: `income_total`, `expense_total` (confirmed only), `balance`. Endpoints: `POST/GET /incomes` (filters date range + source), `GET/PATCH/DELETE /incomes/{id}`, `GET/PATCH /me`, `GET /balance`. Daily summary gained `earned_today`, `earned_this_month`, `balance`; monthly gained `earned_total`, `balance` (additive, contract intact). App: Expense/Income switch on the add form, balance headline with spent/earned today, incomes in today's list, earned and net on the Month tab, opening balance under Categories. 11 new tests (89 total).

**Verified:** curl against local Postgres: schema, CRUD, validation (negative, missing date, unknown source), filters, PATCH null rejection, balance 150 + 575.50 − 12.40 = 713.10, per-user isolation, 401s. Headless mobile Chromium walkthrough: add income → balance and list update, opening balance via prompt, month earned/net, delete recomputes balance. Suite green.

**Known gaps / action needed:** `create_all` does not add columns to existing tables, so the deployed Neon database must be reset (drop tables) before this deploys; data there is test data. Proper migrations (Alembic) are the next infrastructure step if the data becomes real.

## Phase 13a — Migrations

**Status:** done, awaiting owner verification (sync + deploy; nothing to run on Neon)

**Delivered:** Alembic (`alembic.ini`, `migrations/env.py` bound to `SQLModel.metadata` and the app's `DATABASE_URL`). Baseline revision `05abbea478d2` recreates the pre-migration schema, and is a no-op on a database that already has it, so existing deployments are stamped without touching data. `app/database.py`: `alembic_config()` and `run_migrations()`; the lifespan runs `upgrade head` instead of `create_all`. Dockerfile copies `alembic.ini` and `alembic/`. Two tests: migrations applied to an empty database produce a schema with zero autogenerate diff against the models; the baseline preserves rows on a create_all database.

**Verified:** app started against the local create_all database with data: revision stamped, rows intact. Fresh database: tables created by the migration, register returns 201. `alembic current` = head, `alembic check` clean. Suite green (91).

**Known gaps:** none. Deleting a table's enum type on downgrade is handled in the baseline; later revisions must do the same when they add enums.

# Progress

Build order follows `finance-tracker-spec.md` section 6. One phase per commit.

## Decisions (apply to all phases)

- Money is `Decimal` with two places, never float. Rendered as a JSON string (`"12.40"`) so clients never touch binary floats.
- Schema changes between phases use `SQLModel.metadata.create_all` only. When a phase changes the schema, recreate the volume (`docker compose down -v`). No Alembic.
- "Today" for summaries comes from the client's timezone, sent with the request. No server-side default timezone.
- Categories are per user: a seeded default set plus the user's own custom ones.
- LLM provider is a config choice, not a code choice. The categorizer talks to any OpenAI-compatible chat endpoint via the `openai` client; Groq's free tier (Llama 3.3 70B) is the default. Anthropic works by changing `LLM_BASE_URL`/`LLM_MODEL`. Owner's decision, replacing the spec's Anthropic-only wording.

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

**Status:** done, awaiting owner verification

**Delivered:** `users` table (unique username, argon2id hash). `app/security.py`: `hash_password`/`verify_password` (argon2-cffi), `create_access_token` (PyJWT HS256, `sub`=user id, `iat`, `exp`), `get_current_user` dependency (401 + `WWW-Authenticate: Bearer` for missing, malformed, wrong-signature or expired tokens, or a deleted user). `POST /register` (201; 409 on case-insensitive duplicate; username charset validated; password 8–128) seeds the user's default categories in the same transaction via `flush()`. `POST /token` is the OAuth2 password form; one error message for unknown user and wrong password. `categories` gained `user_id` and the unique constraint is now `(user_id, name)`; `expenses` gained `user_id`. Every expense, category, summary and categorize route requires a token and filters by `user.id`; another user's row is 404 (or 422 when referenced in a body), never 403, so existence is not leaked. Config: `JWT_SECRET` (min 32 chars, app refuses to start otherwise), `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` (default 30 days, since the widget has no refresh flow). Startup seeding removed.

**Verified:** schema via psql (argon2id hashes stored, `$argon2id$v=19$m=65536,t=3,p=4`; unique `(user_id, name)`; FKs). Register: 201, duplicate `Vlad` 409, short password 422, `bob smith` 422. Token: wrong password 401, unknown user 401 with identical message. Protected routes: no token 401 with `WWW-Authenticate`, garbage 401, expired 401, wrong-secret 401. Two users each get 8 seeded categories with distinct ids. Cross-user: creating an expense in another user's category 422; GET/PATCH/DELETE another user's expense 404; DELETE another user's category 404; both users can own a "Coffee". Summaries and `/categorize` return only the caller's data. `/health` remains public. Weak `JWT_SECRET` fails at import with a clear validation error. App log contains no passwords.

**Known gaps:** no token refresh or revocation (out of spec). Schema changed: `docker compose down -v` required.

## Phase 7 — Tests

**Status:** not started

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

## Phase 11b — Android app and widget

**Status:** done, built and verified by owner on a Galaxy S25 (Android 16). Two fixes were needed at build time: compileSdk raised to 36 (androidx.browser 1.9.x requires it) and the token store rewritten for the stable security-crypto 1.0.0 API (MasterKey.Builder only exists in the 1.1.0 alphas).

**Delivered:** `android/` Gradle project (AGP 8.9.2, Gradle 8.11.1 wrapper, Kotlin 2.1.21, minSdk 26, compileSdk 35). The app is a Trusted Web Activity: `com.google.androidbrowserhelper.trusted.LauncherActivity` declared in the manifest with the server URL as metadata, translucent theme, asset statement pointing at the site. The widget is Kotlin + Glance 1.1.1: `Api` (HttpURLConnection, `/token` and `/summary/daily`), `Store` (EncryptedSharedPreferences for token, cached summary, last error), `RefreshWorker` (WorkManager, periodic 30 min + one-shot after login, clears the token on 401), `PamWidget` (balance, spent/earned today, budget left, first target's per-day line, updated time, tap opens the app or the login), `PamWidgetReceiver` (schedules/cancels work), `WidgetConfigActivity` (login dialog on placement). Backend: `/.well-known/assetlinks.json` served from `ANDROID_PACKAGE_NAME` + `ANDROID_CERT_FINGERPRINTS` (404 until set), 3 tests. `android/README.md` covers install, USB debugging, the keytool fingerprint step and layout.

**Verified:** builds and installs from Android Studio; app launches the web client; widget places, logs in and shows the balance; `/.well-known/assetlinks.json` served from the debug keystore fingerprint so Chrome drops its URL bar. Kotlin was never compiled in the build sandbox (no Android SDK, Google's Maven blocked); the two errors above came back from the owner's machine.

**Known gaps:** widget shows only the first target. No adaptive launcher icon (plain vector). Release signing not set up: debug builds only, so `ANDROID_CERT_FINGERPRINTS` holds one fingerprint; a release or Play build adds its own, comma-separated.

## Phase 12 — Income & balance

**Status:** done, verified by owner on Render

**Delivered:** `incomes` table (amount, date, `source` enum work/friend/debt/bonus/other, description, user_id) and `users.opening_balance` (NUMERIC(12,2), may be negative). `app/services/ledger.py`: `income_total`, `expense_total` (confirmed only), `balance`. Endpoints: `POST/GET /incomes` (filters date range + source), `GET/PATCH/DELETE /incomes/{id}`, `GET/PATCH /me`, `GET /balance`. Daily summary gained `earned_today`, `earned_this_month`, `balance`; monthly gained `earned_total`, `balance` (additive, contract intact). App: Expense/Income switch on the add form, balance headline with spent/earned today, incomes in today's list, earned and net on the Month tab, opening balance under Categories. 11 new tests (89 total).

**Verified:** curl against local Postgres: schema, CRUD, validation (negative, missing date, unknown source), filters, PATCH null rejection, balance 150 + 575.50 − 12.40 = 713.10, per-user isolation, 401s. Headless mobile Chromium walkthrough: add income → balance and list update, opening balance via prompt, month earned/net, delete recomputes balance. Suite green.

**Known gaps / action needed:** `create_all` does not add columns to existing tables, so the deployed Neon database must be reset (drop tables) before this deploys; data there is test data. Proper migrations (Alembic) are the next infrastructure step if the data becomes real.

## Phase 13a — Migrations

**Status:** done, verified by owner on Render (baseline stamped, data intact)

**Delivered:** Alembic (`alembic.ini`, `migrations/env.py` bound to `SQLModel.metadata` and the app's `DATABASE_URL`). Baseline revision `05abbea478d2` recreates the pre-migration schema, and is a no-op on a database that already has it, so existing deployments are stamped without touching data. `app/database.py`: `alembic_config()` and `run_migrations()`; the lifespan runs `upgrade head` instead of `create_all`. Dockerfile copies `alembic.ini` and `migrations/`. Two tests: migrations applied to an empty database produce a schema with zero autogenerate diff against the models; the baseline preserves rows on a create_all database.

**Verified:** app started against the local create_all database with data: revision stamped, rows intact. Fresh database: tables created by the migration, register returns 201. `alembic current` = head, `alembic check` clean. Suite green (91).

**Known gaps:** none. Deleting a table's enum type on downgrade is handled in the baseline; later revisions must do the same when they add enums.

## Phase 13b — Accounts & transfers

**Status:** done, verified by owner on Render (first data migration applied in place)

**Delivered:** `accounts` table (name unique per user, `type` enum debit/cash/other, free-text `subtype` for the bank, `opening_balance`), `account_id` on expenses and incomes (defaults to General), `transfers` table (from/to accounts, amount, date, description). `users.opening_balance` removed. Migration `4004c26c965e` creates a General account per existing user carrying their old opening balance, backfills every expense and income onto it (nullable column → backfill → NOT NULL), and its downgrade restores `users.opening_balance` from General. `services/accounts.py` seeds General at registration; `services/ledger.py` computes per-account balances (opening + income − expenses + transfers in − transfers out) with four GROUP BY queries. Endpoints: `/accounts` CRUD (General protected; delete folds opening balance, expenses, incomes into General, drops transfers between the two, re-points transfers with third accounts), `/transfers` CRUD (from ≠ to, both must be the caller's), `account_id` filters on `/expenses` and `/incomes`, `/balance` and `/summary/daily` gain `accounts`. `PATCH /me` removed (opening balance lives on accounts). App: account picker on expense and income forms (remembers last used), Transfer segment, per-account chips under the balance, transfers in today's list, Accounts tab (add / tap-to-edit / delete, Log out moved here). 16 new tests (107 total), including the data-migration test.

**Verified:** app started against the local database at the baseline revision with data: migration ran, every user got General with their opening balance, no null account_ids. curl: create/duplicate/bad-type accounts, expense and income on a chosen account, default to General, foreign account 422, transfer create/filter/patch/same-account 422, balances per account with total unchanged by transfers, rename/opening patch, General delete 409, account delete folding (total unchanged before/after). Headless mobile walkthrough: add account, edit General's opening, transfer between accounts, chips and list update, logout from Accounts tab. Suite green. Migration down/up round trip on a populated scratch DB.

**Known gaps:** no credit-card accounts yet (enum change is a one-line migration when wanted). Account edit form uses the same card as add; fine on mobile.

## Phase 13c — Targets

**Status:** done, verified by owner on Render

**Delivered:** `targets` table (name, amount = balance to reach, start_date, end_date, `start_balance` snapshot) via migration `e890c56b0580`. `services/targets.py` is pure: `target_progress(target, current_balance, today)` returns remaining, days total/elapsed/left (inclusive), `required_per_day` (remaining ÷ days left, rounded up to the cent), `expected_balance` on the straight line from start balance to goal, `projected_balance` and `projected_date` from the average daily change so far, and a status of on_track / behind / achieved / expired. Endpoints: `POST/GET /targets` (progress computed on read against the live balance; `tz` decides today), `GET/PATCH/DELETE /targets/{id}`. Daily summary gains `targets` (additive). App: a Targets card on the Today tab with progress bar, "€X/day" and "at this pace done <date>", status chip, set and delete. 17 new tests (124 total), 10 of them pure maths cases including rounding, last day, achieved, expired, falling balance and pace-from-start-balance.

**Verified:** live curl: 30-day target €300 above balance → €10.00/day; €60 income → €8.00/day, on track; PATCH amount down → achieved; end before start → 422; summary carries targets. Headless walkthrough: set target, per-day figure drops after adding income, status chip renders. Suite green.

**Known gaps:** targets are balance-based only (the owner's choice); an "earned since start" variant would be one enum field. No edit form in the app; PATCH exists in the API.

## Phase 14 — Notebook restyle

**Status:** done, awaiting owner verification on the phone

**Delivered:** `app/static/styles.css` rewritten around semantic tokens with a
light and a dark theme (`prefers-color-scheme`), plus `app/static/fonts.css`:
Inter (400/600/700) and Caveat (500/700), subsetted to the characters the app
renders and embedded as base64, 184 KB, no third-party request. Handwriting is
restricted to titles, labels, status pills, buttons and empty states; every
figure, row title and secondary amount is Inter with tabular figures. Paper
grain, a red margin rule, washi tape that varies by card, and a spiral binding
with a punched-hole shadow on the cover. Hand-drawn SVG masks for the title
squiggle, the circle around an overspent amount, the achieved checkmark and the
delete cross. Motion under 250ms: page-turn on view change, ink-fill on bars,
a press state on buttons, all off under `prefers-reduced-motion`. Icon, manifest
colours and the two `theme-color` metas updated. Style guide in `docs/STYLE.md`.

**Verified in the browser at 390px, both themes:** every amount column starts at
the same pixel (253.1) and every progress bar is the same width (198.6); the
smallest control is 44px; no horizontal overflow; twelve text styles measured
against their composited background all clear WCAG AA (worst case 5.56 light,
5.65 dark). The full functional walkthrough still passes end to end with no
console errors, and the suite is green.

**Known gaps:** no in-app theme toggle, the theme follows the system. The
month-change animation is the generic view transition, not a true page flip.

## Fix — default account identified by a flag

Found while seeding demo data for the restyle: renaming the seeded "General"
account to a real bank name broke every expense or income created without an
explicit account, because the fallback was looked up by that literal name and
raised, surfacing as a 500. Accounts now carry `is_default`, set at
registration and backfilled by migration `cdf791184e60` for the oldest account
of each existing user; the delete guard and the client's protected row read the
flag. Regression test added.

## Navigation and identity pass (Money Manager layout)

**Why:** the cover had to carry the brand and four section tabs at once, so at
360px it ran out of room; the app also had no mark of its own. Owner asked for
the control scheme of Money Manager (Realbyte) — identity on top, navigation at
the bottom.

Sections moved out of the header into a fixed bottom bar, each tab a pen-drawn
icon over its label, the open one in ink-blue with a 3px marker on its top edge.
The cover now holds only the logo, the name, and the title of the screen you are
on. The logo is a ruled notebook with three ascending bars, drawn once as an SVG
mask so it takes the colour under it; the same mark is the app and launcher
icon. The four supporting figures became a ruled 2×2 ledger strip, and each row
grew a coloured stroke down its left edge keyed off the amount with `:has()`,
so income, transfers and overspends read at a glance without an extra class.

Fixes that came out of measuring it at 360px: grid items default to
`min-width: auto`, so a long figure was stretching the card past the viewport
and dragging the fixed bar with it — cards, card children and ledger cells are
now `min-width: 0`, and the balance and supporting figures are `clamp()`ed.
Selects that carried long words (the category list) got 1.45× the width of the
field beside them. Account rows dropped the opening balance from the subtitle
(it is in the edit form, where it can be changed) and no longer repeat the bank
in the title. A row with no delete button reserves that column so amounts stay
on one right edge — but only in a list that has delete buttons at all, otherwise
the whole list gave up 44px for nothing.

**Verified at 360px, both themes:** no horizontal overflow (`scrollWidth` 360 =
`clientWidth`), header and bottom bar both fit without scrolling, smallest
control 58px, every amount at the same pixel (223) and every bar the same width
(158), last card clears the bar by 461px. Twelve text styles re-measured against
their composited backgrounds: all clear WCAG AA (worst 5.56 light, 5.65 dark).
Full functional walkthrough passes with no console errors; 128 tests green.
README screenshots re-shot at 360px.

**Known gaps:** no in-app theme toggle. Screenshots are headless renders, not
photographs of the phone.

## The home screen becomes a history, adding moves behind a "+"

**Why:** the home screen only listed today, so yesterday's purchases were
unreachable without the Month tab, which shows category totals rather than
entries. The add forms also took the top third of the screen every time.

`#today-list` is gone; the home screen now renders `#feed`: expenses, incomes
and transfers over a rolling window, newest first, cut into days. Each day is
headed by a Caveat date rule carrying that day's spend and, when there is any,
that day's income. Transfers are listed under the day but never counted into
its totals, because moving money between your own accounts is neither spending
nor earning. The window starts at 30 days and "Earlier" widens it by 30 at a
time; rather than guessing whether anything is back there, the button widens,
compares the row count, and settles on "Nothing earlier" when nothing changed.

The three add forms moved into a bottom sheet opened by a floating "+".
It closes on the scrim, the cross, Escape or a successful add, and it locks the
page behind it. One subtlety worth knowing: `main` is its own stacking context
(it has to sit above the desk grain), so a `z-index` inside it could never beat
the navigation — the view itself is raised while the sheet is open.

Two date bugs surfaced while building the day headers. `new Date("2026-09-20T00:00:00")`
parses as *local* midnight, so calling `.toISOString()` on it in any zone east
of UTC gives the previous day — "Yesterday" was landing a day early and the
feed window started a day too soon. Date arithmetic now goes through one
`isoDate`/`shiftDays` pair, the same offset correction `todayISO` already used.

**Verified at 360px, both themes:** no horizontal overflow, header and bar fit,
smallest visible control 58px, amounts and bars aligned to the pixel. The sheet
sits above the navigation, its close target clears the segmented control, and
the panel ends at the viewport edge. Sixteen text styles measured against their
composited backgrounds, including the day rule, day total, "Earlier" and the
"+": all clear WCAG AA (worst 5.56 light, 5.65 dark). A dedicated probe covers
the sheet round trip (open, add, auto-close, feed grows, body unlocked) and
"Earlier" running out of history; the full walkthrough passes with no console
errors; 128 tests green.

**Known gaps:** no in-app theme toggle. The feed has no filter or search yet —
reaching a specific old purchase means widening the window. Screenshots are
headless renders, not photographs of the phone.

## Targets move to the month tab

**Why:** targets sat at the bottom of the home screen, which is now an
unbounded history — with a few weeks of entries they were unreachable.

They moved under the category budgets on the Month tab, which is the screen
that already answers "am I on course this month". The daily summary still
carries `targets` (the Android widget reads them there, and the contract only
allows additions), but the client no longer renders them from it: the month
view calls `GET /targets?tz=` on mount, and adding or deleting one refreshes
that list rather than the whole summary.

**Verified:** the walkthrough now sets a target on the Month tab, checks the
home screen has no target form at all, adds income on the home tab, and comes
back to Month to see the per-day figure drop from €34.37 to €17.70 with the
status chip reading "On track". Amounts stay aligned, the smallest control is
44px, all thirty-two contrast measurements pass, 128 tests green.

## Fix — an abandoned request must not become an error toast

**Reported:** "часто снизу пишет ошибку Cannot set properties of null (setting
value)", plus the bottom bar sliding out of reach on the phone.

The view is replaced whole on every tab switch, so any element looked up before
an `await` can be detached by the time the response lands. Writing to a
detached node throws, the throw is caught by the handler, and the handler
toasts it — so a perfectly successful action ended in a red error. The slow
free-tier suggestion made this frequent: ask for a category, get bored, switch
tab, get an error for a request that worked.

Fixed with one `live(el)` helper (`el.isConnected ? el : null`) and a guard at
every write that happens after an `await`: `suggest()` now returns early when
its form is gone, the four add handlers reset the form only if it is still
there, and "Earlier" only touches its button if it is still on screen. The
request itself is never abandoned — the expense still lands, the feed and the
summary still refresh when you come back.

`design/raceprobe.mjs` holds each request open, switches tab while it is in
flight and asserts no error is ever shown. Against the old code it reports
exactly the reported message for the suggestion, the expense and "Earlier",
plus `Cannot read properties of null (reading 'reset')` for the target; against
the fixed code all four are silent and the work still lands.

The bottom bar itself is `position: fixed` and measured stuck at every scroll
position, so the reported scrolling is the Android keyboard: by default it
shrinks only the visual viewport, leaving a fixed bottom bar below the fold.
The viewport meta now carries `interactive-widget=resizes-content`, which
shrinks the layout viewport instead, and the sheet is capped in `dvh` rather
than `vh` so its submit button stays reachable with the keyboard up. The toast
also moved above the bar instead of being drawn across it.

**Verified:** four-case race probe silent, nav fixed at scroll 0 / 900 / bottom,
toast clears the bar by 7px, walkthrough clean, thirty-two contrast
measurements pass, 128 tests green.

## Fix — a deploy that never reached the phone

**Reported:** installing the app gave an older build; deleting and installing
again gave a different, still-not-current one.

`StaticFiles` answers with `ETag` and `Last-Modified` but no `Cache-Control`,
which lets a browser apply heuristic freshness (RFC 9111 §4.2.2): with no
explicit policy it may reuse a cached copy for about a tenth of the file's age
*without contacting the server at all*. On a deploy that has been live a week
that is most of a day per file. An installed PWA is served by the same browser
cache, so uninstalling the app does not clear it — hence the same stale build
after a reinstall. Worse, each file ages on its own clock, so the second
install could pair a revalidated `index.html` with a cached `app.js`, which is
its own source of null errors on top of the real race fixed above.

`app/webclient.py` mounts the client through a `StaticFiles` subclass that
states a policy per file. `index.html` and `manifest.json` are `no-cache` —
always revalidated, and an unchanged shell answers 304 from an in-memory ETag.
The shell's links are rewritten at start-up to carry the content hash of the
file they point at (`app.js?v=b606c119`), and a file asked for by its own hash
is `public, max-age=31536000, immutable`. Anything asked for without the right
hash falls back to `no-cache`, so the safe answer is the default and only a
fingerprinted URL earns the fast one. A deploy changes the bytes, the hash and
therefore the cache entry: nothing has to expire.

**Note for the already-installed phone:** the *old* `index.html` is still in
the browser cache under the old heuristic, so this fix cannot reach it by
itself. One clear of the site's data (Chrome → Site settings → the site →
Clear & reset), or one hard reload, and it never happens again.

**Verified:** five tests in `tests/test_static.py` cover the shell being
revalidated, the links carrying the real hash of each file, a hashed URL being
immutable, an unhashed or stale one falling back to `no-cache`, and an
unchanged shell answering 304. Measured over HTTP as well. Walkthrough and both
probes clean, 133 tests green.

## Receipt scanner

Photograph a receipt and the expense form fills itself in. `POST /receipts/scan`
takes a multipart image, hands it to a vision model inline as a `data:` URL,
and returns `{total, merchant, date, category, fell_back}`. It creates nothing:
the user confirms the suggestion and adds it like any other expense.

**The photo is never stored.** It is read into memory for the length of the
call and dropped — not to disk, not to the database — and because it is sent
inline rather than uploaded, there is nothing left at the provider to delete
either. The client shrinks it first, to 1600px on the long edge and JPEG 0.82:
a 2400×3200 camera photo left the phone as about 25 KB in the probe. The API
still bounds what one request may cost (`RECEIPT_MAX_BYTES`, 4 MB, 413 over it)
and refuses anything that is not JPEG, PNG or WebP with a 415 before a token is
spent.

**What is trusted and what is checked.** The total is the one number taken from
the model, because reading it off the paper is the whole point — but it is
validated as money: a positive decimal, quantized to two places, or the scan is
refused with a 422 ("Could not read a total on this receipt") rather than
guessed at. The date must parse as ISO and must not be more than a day in the
future, otherwise it is dropped and the client falls back to today. The
merchant is whitespace-collapsed and capped at 120 characters. The category
must match one of the user's own exactly, same rule as the text categorizer: a
near miss is a miss and falls back to `uncategorized` with `fell_back: true`.
The model is asked for bare JSON and its answer is accepted wrapped in a code
fence too, because that is the one deviation every provider makes.

Vision gets its own model name and timeout in config (`LLM_VISION_MODEL`,
`LLM_VISION_TIMEOUT_SECONDS`, 45s) so the provider stays a configuration
choice and a slow picture does not force the text categorizer to wait as long.

**Verified:** 36 tests — the endpoint (a good scan, nothing written, an
invented category falling back, another user's categories never offered, an
unreadable total, a non-JSON answer, a wrong media type, an oversized photo, an
empty photo, a provider failure, and no token) plus the parsers (totals as
string/float/comma/currency-prefixed, rejects for null/blank/zero/negative/bool,
fenced JSON, non-object answers, dates kept/future-dropped/unparseable, merchant
tidying, exact category matching). `design/scanprobe.mjs` drives it in a real
browser: it draws a 2400×3200 receipt on a canvas, hands it to the file input
the way a camera would, and checks the form comes back filled
(12.40 / Groceries / SuperValu Rathmines / 2026-09-18) and that confirming it
adds a normal expense. 169 tests green, thirty-four contrast measurements pass,
the walkthrough and both race probes are clean.

**Known gaps:** no line-item breakdown, only the total — splitting one receipt
across categories is a bigger feature and was not asked for. Nothing detects
that the same receipt was scanned twice.

## Fix — the scanner on a real receipt, and picking from the gallery

**Reported:** a Romanian supermarket receipt came back "Could not read this
receipt. Type it in yourself." That message is the `parse_answer` path, so the
model replied with something that was not JSON — four separate causes were in
play, all of them fixed:

1. **A truncated answer looked like a bad answer.** The vision call had a
   200-token budget, and a model that reasons before it replies can spend the
   whole of it before the JSON starts. `_chat` now raises on
   `finish_reason == "length"` with "The model's answer was cut off" instead of
   handing half an object to the parser, logs the truncated text, and the
   budget is 500.
2. **Bare JSON was demanded, not found.** Providers wrap the object in a code
   fence, or in a sentence, or add a note after it. `extract_json` now picks
   the first balanced `{...}` out of whatever came back, skipping braces inside
   strings so a merchant called `{Spar}` does not confuse it.
3. **The print was on the edge of legible.** A supermarket receipt is long,
   thin and photographed from a distance; at 1600px its lines were marginal.
   The client downscales to 2000px at quality 0.85 now — about 40 KB instead of
   25 KB, which is nothing next to a failed read.
4. **The receipt was in lei.** Every amount in the app is euro and nothing
   converts, so reading 57.90 RON as €57.90 would have put a wrong number in
   the ledger. The model is now asked for the currency, and a stated non-euro
   one stops the scan with "This receipt is in RON. PAM keeps everything in
   euro, so add it by hand." An absent answer still carries on as euro, since
   the model cannot always find one and most of these receipts are Irish. The
   prompt also says a receipt may be in any language and names what the total
   line can be called.

**Also asked for:** choosing a photo from the gallery instead of taking one.
The two halves of the scan slot share one file input; `capture="environment"`
is added before the click for the camera and removed for the gallery, which is
the whole difference on Android.

**Verified:** 21 new tests (the currency guard, JSON extraction out of chatter
and nested objects, the truncation guard in the provider wrapper, and that the
picture is sent inline with its own media type). `design/scanprobe.mjs` now
also asserts each button sets `capture` correctly and both halves are 44px.
190 tests green, thirty-six contrast measurements pass, walkthrough and both
race probes clean.

**Still unverified:** whether the Romanian receipt now reads. It cannot be
tested here — there is no vision key in this sandbox, and the stand-in model
answers from a script. The next real failure will say which of the four it was.

## Fix — the vision budget has to pay for the thinking

The previous fix did its job: the Romanian receipt now fails with "The model's
answer was cut off" rather than the generic message, which names the cause.
Gemini reasons before it answers, and on the OpenAI-compatible endpoint those
reasoning tokens are spent out of `max_tokens` — so a 500-token budget was
gone before the first character of JSON.

The budget is now `LLM_VISION_MAX_TOKENS`, default 2000. The answer itself is
about sixty tokens; the rest is head-room for thinking. Deliberately not fixed
by turning thinking off, because every provider spells that differently and
this project keeps the provider a configuration choice, not a code one.

If it ever truncates again the server log says so outright, with the budget and
the text that did arrive, and `completion_tokens` on the ordinary `llm ...`
line shows how much the model actually wanted.

## Foreign receipts are converted, not refused

Refusing a receipt in lei was the safe answer, not a useful one. It is now
converted to euro and the form is filled with the euro amount, because the
ledger has exactly one currency and always will.

**Where the rate comes from.** The European Central Bank's euro reference
rates: free, no key, no sign-up, and the rate a set of Irish books would
actually use. The ninety-day file rather than today's, so a receipt is
converted at the rate in force **the day it was printed**, not the day it was
photographed. The ECB publishes on working days only, so a Saturday receipt
takes Friday's rate — the nearest published day at or before it, which is what
an accountant does. A currency missing on its own day falls back the same way.

**What is kept.** Only the euro amount, as an ordinary expense. The rate is
not stored; the scan response carries the original amount, its currency, the
rate and the day the ECB published it, and the client shows all four —
"Read 57.90 RON → €11.41 (ECB Sep 18, 5.0755/€)" — so the number in the form
never looks like it came from nowhere.

**When it cannot.** A currency the ECB does not publish (UAH, for one) is a
422 saying so by name, rather than a silent wrong number. If the ECB cannot be
reached, the last good table keeps being served: a day-old reference rate beats
refusing to read the receipt. Only with nothing cached at all does the scan
fail.

The split follows the rest of the project: `app/ecb.py` fetches and caches,
`app/services/fx.py` parses, picks the day and divides, with no I/O.

**Verified:** 22 new tests — reading the ECB's real file shape past its two
namespaces, skipping a broken row without dying, a day's own rate, the weekend
fallback, a currency missing on its day, a date before the file starts, an
unpublished currency, four conversions including one currency stronger than the
euro and an amount that rounds to nothing, plus the cache: fetched once,
refetched when stale, stale copy served when the ECB is down, and an error only
when there is nothing cached. The browser probe now scans a Romanian receipt
end to end and checks the form fills with 11.41 and the note shows its working.
212 tests green, thirty-six contrast measurements pass.

**Not verified here:** the live ECB endpoint. The sandbox's proxy blocks
www.ecb.europa.eu, so the tests and the browser probe run against the ECB's own
file shape served locally. The first real scan of a foreign receipt is the
proof; the server log prints "ECB rates loaded: N days, latest YYYY-MM-DD" when
the file arrives.

## The hryvnia, which the ECB does not quote

Asked for: Ukrainian receipts. The ECB publishes euro reference rates for
about thirty currencies and the hryvnia is not one of them, so it gets its own
central bank — the NBU's exchange directory, which is free, needs no key, and
has exactly the standing for the hryvnia that the ECB has for the euro. It
answers one date at a time and quotes hryvnia per euro, which is already the
convention here, so no cross rate is involved.

**How the two fit together.** A small `Chain` asks each source in turn and
moves on **only** when a source says it does not quote that currency at all.
That distinction is the whole design: a currency the ECB does quote but not on
some particular day is a gap in the ECB, not a job for a Ukrainian bank, so
`CurrencyNotPublishedError` is a separate class from the plain unavailable
error. Asking the NBU about lei would be nonsense, and a test asserts it never
happens.

Only the hryvnia goes through the NBU. Another currency the ECB skips is
reported as unsupported by name rather than guessed at through a cross rate;
"VND is not a currency PAM has a euro rate for" is a better answer than a
number nobody can check.

The rate now carries which bank said so, through `Conversion` and into the
client, because "ECB Sep 18" on a rate the ECB never published would be a lie.
The note reads "Read 500.00 UAH → €10.31 (NBU Sep 18, 48.5031/€)".

**Verified:** 17 more tests — the NBU's row read as hryvnia per euro, its own
`exchangedate` winning over the date asked for, six malformed answers refused,
the per-day cache and the request it actually sends, other currencies never
reaching it, an unreachable bank being an error rather than a guess, and four
chain cases including the gap that must not fall through. The browser probe
scans a Ukrainian receipt end to end and the form fills with €10.31. Two
`caplog` assertions pin the log lines, since this sandbox's stdout never
reaches the log file after start-up and they could not be read there.
229 tests green.

**Not verified here:** the live NBU endpoint, blocked by the sandbox's proxy
exactly like the ECB's. Both are exercised against their documented shapes
served locally.

## Notification parsing — the server half

A payment notification from a banking app now becomes a pencilled-in entry the
user taps to confirm. This is the server and web half; the Android listener is
the next phase, and nothing here needs it — the endpoint takes a notification
from anything that can post JSON.

**Pending was already the right shape.** `ExpenseStatus` and the rule that
`confirmed` alone counts towards balances, budgets and summaries were built in
phase one and never used. They are what this feature is made of: what comes
out of `/notifications` is a `pending` expense that moves no number at all
until the user says so. A notification is a rumour about money, not a receipt.

**Money in is not an expense.** The model is asked which way the money went,
and only "out" creates anything. "You received €850" would otherwise become an
€850 spend. Money in is reported (`outcome: "incoming"`) rather than recorded,
because an income has a source the user picks and guessing one from a push
notification is worse than asking. Balance updates, card deliveries, promotions
and login alerts come back as `ignored`.

**The same notification must not land twice.** A listener re-posts when a
notification is updated and again when it restarts, so each carries a key,
unique per user by database constraint, and a repeat returns the expense that
already exists with `outcome: "duplicate"`.

**Two filters, one rule.** The phone decides only whether a notification could
possibly be about money — a number beside a currency marker — and the server
applies the same regex again before spending a token. A message from a friend
never leaves the phone, and never reaches the model if something else calls the
endpoint.

**Which account.** An Android package is something like `com.revolut.revolut`,
so its segments are matched against the user's account and bank names. A miss
falls back to the default account, which is the right answer for cash-like
spending anyway, and the user can change it before confirming.

**Refactor that came with it.** Reading a receipt and reading a notification
are the same job — ask for a small JSON object, then distrust every value in
it — so that half moved to `app/services/answers.py`: pulling the object out
of whatever the provider wrapped it in, and validating money, currency, dates,
text and categories. `receipts.py` and `notifications.py` now hold only their
own prompt and assembly, and the parsing tests moved to `tests/test_answers.py`
where they are tested once rather than twice through two endpoints.

**In the client.** A pending row is drawn pencilled in: dashed left stroke,
grey title, italic amount, and tapping it confirms. It deliberately has no tick
button — a second 44px target in a 360px row truncated the shop name to
"Supe…", which the measurement caught. A note under the list explains the
pencilling, and only appears when something is pending.

**Verified:** 29 new tests — a payment becoming pending, pending counting
towards nothing (`spent_today` and the balance both still 0.00), confirming
putting it in the books, confirming twice being harmless, another user's
pending expense being 404, listing by status, money in and non-transactions
creating nothing, a message never reaching the model at all, the same key
twice making one expense, the same key for two users making two, the account
guessed from the package, an unrecognised app falling back, an invented
category falling back, a foreign payment converted, a provider failure as 502,
an unreadable answer as 422, and eleven texts through the money filter in four
languages. `design/notifyprobe.mjs` posts three notifications into a live
browser session and checks the pending row appears, moves no total, and
confirming it moves €12.40 into `spent today`. 258 tests green, thirty-six
contrast measurements pass, the walkthrough and all three probes are clean.

**Known gaps:** no pending *incomes* — money arriving is reported and dropped.
No mute list yet; that belongs with the phone, which is what learns that an app
never produces money notifications.

## Notification parsing — the Android half

The phone side of the previous phase. Five new files under
`ie.yarodev.pam.notify`, no new dependencies: WorkManager, security-crypto and
AppCompat were already in the build for the widget.

**`MoneyFilter.kt` is the privacy boundary, and it is eight lines.** Android
does not let a `NotificationListenerService` subscribe to particular apps, so
the service sees every notification on the device, messages included. Unless
the text has an amount with a currency next to it, the notification is dropped
before it is stored, queued, sent, or written to the log. A rule small enough
to read in one sitting is a rule that can be trusted with that, which is why
the judgement is crude on purpose: whether it was a payment, which way the
money went, what shop and what category are all the server's job.

**`Captured.kt` keys on content, not on Android's key.** Banks reuse one
notification id for every payment, so `sbn.key` would make two different
purchases collide and the second would be dropped silently. The key is a hash
of app, text and day instead. Its own trade-off — two identical payments in one
day collide — is the smaller one: that is rare and recoverable by hand, where
booking every notification twice would be constant.

**The queue survives no signal.** Captured notifications go into the same
encrypted store as the token and are drained by a WorkManager job, each posted
on its own so one rejection does not block the rest. A rejection from the
server is final and dropped; only a network failure is retried. The queue is
capped at 100, keeping the newest, because after days offline those are the
ones still worth confirming.

**The ignored list populates itself.** The server answers every post with an
outcome, and an app that produces five in a row the server had no use for, and
never a payment, is muted on the phone. A bank that sends balance updates as
well as payments is never muted, because its payments reset the count. That
ordering is the point: the on-device regex costs nothing, so muting exists for
apps that regularly produce money-*looking* text that is not a transaction —
those are what would otherwise cost a request and a token every time.

**Reaching the switch.** A static shortcut (long-press the app icon) and a
`pam://notifications` link from the Accounts tab of the web client, which the
installed app answers and a browser ignores. Two switches on that screen,
Android's own access and PAM's, because granting the permission should not
start anything by itself.

**Two things caught by reading rather than running.** AppCompat inflates
`<Switch>` as `SwitchCompat`, which does not extend `android.widget.Switch`, so
`findViewById<Switch>` would have thrown at runtime — the layout and the field
are `SwitchCompat` now. And `onNotificationPosted` runs on the main thread for
every notification on the device, so the keystore-backed store is opened once
per service rather than once per notification.

**Verified:** the filter's pattern was run against the same eleven cases the
server's tests use, in four languages, and agrees on all of them. The web half
of the change went through the usual battery: 258 tests, thirty-six contrast
measurements, the walkthrough and all four browser probes clean.

**Not verified here:** anything that needs to compile or run on a phone. There
is no Android SDK in this sandbox, so none of the Kotlin has been built. The
APK is the proof, and it needs Android Studio.

## Fix — capture should not require placing a widget

Reported from the phone: the setup screen opened, Android access was granted,
and the capture switch was greyed out with "Set up the widget first".

That gate was mine and it was wrong. The switch needs a *token*, and the token
happened to come only from the widget's login dialog — so someone who wants
notification capture and no widget was asked to place one, on a launcher that
makes widgets awkward. The screen now offers a **Log in** button while there is
no token, which starts the same form the widget uses, and hides it once there
is one. Nothing is duplicated; the existing activity already finished cleanly
when launched without a widget id.

Also from the screenshot: the heading sat under the status bar. The theme has
no action bar, so the screen needed `fitsSystemWindows`.

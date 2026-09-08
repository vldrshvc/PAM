# Personal Finance Tracker — Technical Specification

**Purpose:** A self-hosted personal expense tracker with an API-first backend, smart LLM-based categorization, and an Android home-screen widget. This document specifies *what* to build and *how the pieces fit* — the implementing developer chooses idiomatic details within the stated stack.

---

## 1. Product concept

A single-user (later multi-user) service that:

- Records expenses, each with amount, date, category, and optional description.
- Categorizes expenses automatically from free text ("SuperValu €12.40") using an LLM, choosing from the user's own category list.
- Enforces monthly budget limits per category and flags overspend.
- Exposes a daily summary (spent today, remaining budget) consumable by an Android widget.
- Later: ingests transactions automatically from Revolut and pushes a "confirm & describe" notification to the phone.

The value is the combination: automatic capture + smart categorization + at-a-glance daily state on the home screen. Each part is ordinary; the integrated loop is the product.

---

## 2. Tech stack (fixed)

| Layer | Choice |
|---|---|
| Language | Python 3.10+ |
| Web framework | FastAPI |
| ORM / models | SQLModel |
| Database | PostgreSQL 16 (Docker) |
| DB driver | psycopg2 |
| Auth | JWT (OAuth2 password flow) |
| LLM | Anthropic API (Claude) for categorization |
| Tests | pytest |
| Containerization | Docker + docker-compose |
| Client | Android home-screen widget (KWGT for MVP, native Kotlin/Glance optional) |

---

## 3. Data model

**Category**
- `id` (PK, int, auto)
- `name` (str, unique)
- `monthly_limit` (float, nullable)

**Expense**
- `id` (PK, int, auto)
- `price` (float, required)
- `date` (date, required)
- `category_id` (FK → Category, required; fallback to an "uncategorized" category)
- `description` (str, nullable)
- `status` (enum: `pending` / `confirmed`, default `confirmed` for manual entry) — used later for auto-ingested transactions awaiting user confirmation

**User** (added in auth phase)
- `id` (PK, int, auto)
- `username` (str, unique)
- `hashed_password` (str)
- Expenses reference `user_id` once multi-user is enabled.

Relationships: an Expense belongs to one Category (and one User). A Category has many Expenses.

---

## 4. API surface

Build incrementally. Endpoints, grouped by phase:

**Core**
- `GET /health` — liveness probe, returns `{"status": "ok"}`
- `POST /expenses` — create an expense; validates body against the Expense schema; persists; returns the created record with its `id`
- `GET /expenses` — list expenses; support query filters (by date range, by category)
- `GET /expenses/{id}` — single expense
- `PATCH /expenses/{id}` — edit
- `DELETE /expenses/{id}` — remove

**Categories**
- `GET /categories` — list
- `POST /categories` — create custom category
- `DELETE /categories/{id}` — remove (reassign its expenses to "uncategorized")

**Budget & summary**
- `GET /summary/daily` — spent today, per-category remaining budget, and one aggregate figure; this is the widget's data source
- `GET /summary/monthly` — spend per category vs limit, overspend flags

**LLM categorization**
- `POST /categorize` — body: raw text (e.g. "SuperValu €12.40"); returns a category chosen strictly from the current category list, plus parsed amount if present; falls back to "uncategorized" on low confidence

**Auth** (added later)
- `POST /register`, `POST /token` (login → JWT), and protection on all expense/category/summary routes so a user sees only their own data

---

## 5. Architecture notes for the implementer

**Database access.** One `engine` created from a connection string held in an environment variable (never hardcoded). Per-request `Session` for reads/writes; commit on write; the connection string is the only thing that changes between local Docker and a remote/cloud Postgres.

**Config & secrets.** Everything sensitive (DB connection string, Anthropic API key, JWT secret) lives in `.env`, excluded via `.gitignore`. No secret ever committed.

**LLM categorization contract.** The model receives the raw expense text *and the user's current category names*, and must return exactly one of them. Prompt is constrained ("respond with only one category from this list"). The endpoint parses and validates the response against the live category list; anything unmatched → "uncategorized". The LLM never invents categories and never sees data beyond what the request supplies. Use a cheap model for this task; reserve larger models for cases where quality changes the outcome.

**Pending/confirmed status.** Manual entries are `confirmed` immediately. The status field exists so that, in the Revolut-ingestion phase, auto-created expenses land as `pending` until the user confirms and adds a description via the push notification.

**Daily summary as the client contract.** `GET /summary/daily` returns a single, stable JSON shape. The Android widget only ever calls this one endpoint. Keeping the widget "thin" (display only) means all logic stays server-side and the client can be swapped (KWGT → native) without backend changes.

---

## 6. Build order (phased)

1. **Core skeleton** — FastAPI up, `/health`, Expense model, in-memory list to prove CRUD flow.
2. **Persistence** — PostgreSQL in Docker (with a named volume so data survives container recreation); SQLModel table; rewrite endpoints to read/write via Session. Data now survives restarts.
3. **Categories** — Category table, FK from Expense, custom category management, seed defaults, "uncategorized" fallback.
4. **Budget & summaries** — full CRUD on expenses, monthly limits, overspend flags, daily/monthly summary endpoints.
5. **LLM categorization** — `/categorize` endpoint; API key in `.env`; constrained prompt; validate against live categories.
6. **Auth** — JWT, per-user data isolation, protected routes.
7. **Tests** — pytest over core logic (creation, categories, budget math, categorization with the LLM mocked); separate test database.
8. **Packaging & deploy** — `.env` for all secrets, `.gitignore`, `requirements.txt`, app Dockerfile + full docker-compose, deploy to a host (Railway / Fly.io / VPS), clean README with setup, stack, screenshots, example requests.

**v2 (optional, high-impact):**
9. **Auto-ingestion** — Revolut integration (Open Banking API or webhook) creating `pending` expenses.
10. **Confirm-and-describe** — server-initiated push (FCM) to the phone; user confirms, picks category, adds description; expense becomes `confirmed`.
11. **Android widget** — home-screen widget calling `GET /summary/daily`; KWGT for MVP or native Kotlin/Glance.

---

## 7. Constraints & standards

- One concern at a time; a phase ships only when the previous one works end to end.
- Secrets exclusively via environment variables; nothing sensitive in version control.
- Named Docker volume for the database; never store DB data inside the container.
- `GET` for reads, `POST`/`PATCH`/`DELETE` for state changes — REST semantics respected.
- Tests before calling the project done; deployable via docker-compose from a clean checkout.

---

## 8. Definition of done (portfolio-grade)

- Runs from a clean clone with `docker compose up` + documented steps.
- Data persists across restarts.
- All core + category + budget + summary + categorization + auth endpoints working.
- pytest suite green.
- Deployed to a public URL.
- README with stack, setup, screenshots, and example requests.

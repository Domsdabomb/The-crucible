# CLAUDE.md — The Crucible (v2 Backend)

## Project Overview

**The Crucible** is a Flask web application for managing a tech repair shop. This repository is the v2 rewrite of the `invoicetosms` repo — it uses a proper Blueprint architecture, a stricter 10-state job lifecycle with a validated state machine, a separate `devices` entity, per-job parts tracking, technician assignment, session-based admin authentication, a Crucible Coin loyalty wallet, invoicing, and all money stored as integer cents.

> **Note:** this file previously described an early snapshot of the project (no auth, no wallets/invoices). It has been rewritten to match the code as it actually stands — treat this version as authoritative.

---

## Architecture

```
the-crucible/
├── run.py                  # Dev entry point: python run.py
├── serve.py                # cwd-agnostic entry point for preview tools / IDE launch
├── app/
│   ├── __init__.py         # Flask app factory (create_app) — DB, blueprints, CSRF protection
│   ├── db.py                # SQLite helpers: get_db, close_db, init_db, flask init-db CLI
│   ├── admin/
│   │   ├── __init__.py     # Blueprint: admin_bp, url_prefix="/admin"
│   │   └── routes.py       # All admin routes (jobs, customers, technicians, parts, invoices, wallets, SMS log)
│   ├── auth/
│   │   ├── __init__.py     # Blueprint: auth_bp, url_prefix="/auth"
│   │   └── routes.py       # login / logout / first-run setup
│   ├── services/
│   │   ├── auth.py          # Password hashing (werkzeug PBKDF2) + login_required decorator
│   │   ├── crypto.py        # Fernet encrypt/decrypt for device passcodes at rest
│   │   ├── sms_service.py   # SMS stub: send_sms, sms_intake, sms_ready
│   │   └── wallet.py        # Crucible Coin loyalty wallet: earn/spend/redeem logic
│   └── templates/
│       ├── base.html
│       ├── auth/
│       │   ├── login.html
│       │   └── setup.html
│       └── admin/
│           ├── dashboard.html
│           ├── job_list.html / job_detail.html / job_new.html
│           ├── customer_list.html / customer_detail.html
│           ├── technician_list.html / technician_create_login.html
│           ├── invoice_list.html / invoice_detail.html / invoice_new.html
│           ├── wallet_list.html / wallet_detail.html
│           └── sms_log.html
├── db/
│   └── schema.sql          # Full SQLite schema (11 tables, indexes, trigger)
├── tests/                   # pytest suite — see Testing section below
│   ├── conftest.py
│   └── test_*.py
├── .claude/
│   └── launch.json          # Claude Code preview: python run.py on port 5000
├── pytest.ini
├── requirements.txt         # flask, cryptography (Fernet), pytest
└── .gitignore
```

---

## Tech Stack

- **Python 3.12 / Flask 3.x** — app factory + Blueprint pattern
- **SQLite 3.35+** — raw `sqlite3`, no ORM; uses GENERATED columns and WAL mode
- **werkzeug.security** — password hashing (PBKDF2-SHA256), ships with Flask, no extra dependency
- **cryptography (Fernet)** — symmetric encryption for device passcodes at rest
- **stdlib `urllib.request`** — SMS HTTP stub (no extra dependencies yet)
- **Jinja2** — templating (built into Flask)
- **pytest** — automated test suite (`tests/`)

No Twilio dependency. SMS is currently a stub that POSTs to a placeholder `invoicetosms.com` URL. The real provider and API key aren't wired up yet.

---

## Database Schema

The schema lives in `db/schema.sql` and is applied via `flask init-db` (or `init_db()` in code). It uses `CREATE TABLE IF NOT EXISTS` — **running init-db drops and recreates all tables** (see `init_db()` in `app/db.py`).

| Table | Purpose |
|---|---|
| `technicians` | Staff who perform repairs; can be activated/deactivated |
| `customers` | Name, phone (E.164, unique), email |
| `devices` | One device per repair; FK to customer |
| `repair_jobs` | Core table — device + customer + tech + lifecycle state + pricing |
| `job_status_history` | Append-only audit log of every status transition |
| `parts` | Parts ordered/installed per job |
| `sms_log` | Every SMS attempt: queued/sent/delivered/failed |
| `wallets` | Crucible Coin loyalty balance, one per customer |
| `wallet_transactions` | Append-only ledger of coin credits/debits |
| `invoices` | Snapshot of a job's pricing at invoice time, with coin discount applied |
| `admins` | Login accounts for the admin panel |

**Key design decisions:**
- **Phone is the customer upsert key** — `customers.phone` is UNIQUE; intake updates name/email if phone already exists.
- **Money is stored as integer cents** — avoids floating-point drift; all `*_cents` columns. `repair_jobs.total_cents` and `invoices.subtotal_cents` / `amount_due_cents` are `GENERATED ALWAYS AS` columns.
- **WAL mode** — `PRAGMA journal_mode = WAL` is set on every connection in `get_db()`.
- **Device passcode** is encrypted at rest with Fernet (`app/services/crypto.py`) — `job_new` encrypts on write, `job_detail` decrypts for display. Never read/write `devices.passcode` directly without going through `encrypt_passcode`/`decrypt_passcode`.
- **Passwords** are hashed with `werkzeug.security.generate_password_hash` (PBKDF2-SHA256, salted). Do not roll custom hashing here.

---

## Job Lifecycle (10 states)

```
received → diagnosed → awaiting_parts → in_repair → quality_check → ready → picked_up
                     ↘ cancelled ↗                                   ↓
                                                               warranty_return → in_repair
                                                                              → closed
```

State transitions are **strictly enforced** by `ALLOWED_TRANSITIONS` in `app/admin/routes.py`. The route returns HTTP 422 if an illegal move is attempted. `closed` is a terminal state with no exits.

**SMS auto-fires** on two transitions:
- `received` (intake): `sms_intake()` sent immediately after job creation
- `→ ready`: `sms_ready()` sent when status moves to `ready`

**Coins auto-award** on one transition:
- `→ picked_up`: `reward_job_pickup()` credits 5 flat coins + 1 coin per $10 of `total_cents` (see Crucible Coin section below). A reward failure does not block the status update.

---

## Authentication

Session-based admin login lives on the `auth` Blueprint (`/auth/login`, `/auth/logout`, `/auth/setup`).

- **First run**: if no row exists in `admins`, `/auth/login` redirects to `/auth/setup` to create the first account.
- **Passwords**: hashed with `werkzeug.security.generate_password_hash` / verified with `check_password_hash` (see `app/services/auth.py`). Minimum 8 characters, enforced at setup.
- **Session**: `session["admin_id"]` / `session["admin_username"]` are set on login/setup and cleared on logout.
- **`login_required`** decorator (`app/services/auth.py`) guards every route on `admin_bp`; unauthenticated requests redirect to `/auth/login?next=<path>`.
- **There is only one account type** — no roles/permissions beyond "logged in or not."

---

## CSRF Protection

All state-changing requests (`POST`/`PUT`/`PATCH`/`DELETE`) are protected by an app-wide CSRF check registered in `app/__init__.py`:

- `csrf_token()` is a Jinja global that lazily generates and stores a per-session token (`session["_csrf_token"]`).
- A `before_request` hook compares `request.form["csrf_token"]` against the session token using `secrets.compare_digest`; a mismatch aborts with 400.
- **Every `<form method="post">` in the templates must include** `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`. If you add a new POST form and forget this, the request will 400.

---

## Testing

`tests/` holds a pytest suite covering the state machine, tax calc, wallet earn/spend/redeem, CSRF enforcement, auth (hash/verify, login/setup flow), `IntegrityError` handling, and passcode encryption (including asserting the raw DB value is never plaintext).

```bash
python -m pytest          # run from the project root
```

Notes for writing new tests (see `tests/conftest.py`):
- The `app` fixture builds a fresh app with a temp-file SQLite DB (not `:memory:` — each `sqlite3.connect()` call gets its own empty `:memory:` DB, which breaks across the multiple connections a test makes) and runs `init_db()`.
- The `no_network_sms` fixture (autouse) monkeypatches `urllib.request.urlopen` so tests never hit the real network even though `sms_service` is a live-HTTP stub.
- CSRF is **not** disabled for tests — use the `csrf_extractor` fixture to pull the token out of a GET response before POSTing, same as a real browser would. Use the `admin_client` fixture for anything behind `login_required`.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes (prod) | Flask session secret; defaults to `"dev-change-in-production"` |
| `PASSCODE_ENCRYPTION_KEY` | Recommended (prod) | urlsafe-base64 Fernet key for `devices.passcode`. If unset, a key is auto-generated into `instance/passcode.key` on first use — fine for dev, but losing that file makes existing encrypted passcodes unrecoverable, so set this explicitly in production. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |
| `INVOICETOSMS_API_KEY` | For SMS | Bearer token for the SMS provider |
| `SMS_SENDER_ID` | No | Sender name shown on SMS; defaults to `"TheCrucible"` |

Config is loaded from `instance/config.py` (silent) — create that file for local overrides. No `.env` file loading; use actual environment variables or `instance/config.py`.

---

## Running Locally

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
flask --app app init-db       # creates instance/crucible.db from db/schema.sql
python run.py                  # dev server on http://127.0.0.1:5000
```

`/` redirects to `/admin/` if logged in, otherwise `/auth/login`. On first run, login redirects to `/auth/setup` to create the initial admin account.

**Alternative entry points:**
- `python serve.py` — cwd-agnostic, safe to launch from any directory
- `gunicorn "app:create_app()" --bind 0.0.0.0:8000` — production

**Claude Code preview:** `.claude/launch.json` is configured to run `python run.py` on port 5000.

---

## Route Map

Admin routes are on the `admin_bp` Blueprint (prefix `/admin`); auth routes are on `auth_bp` (prefix `/auth`). All admin routes require login. Most read routes respond to `Accept: application/json` for JSON output — the `_wants_json()` helper selects response type.

| Method | Route | Function | Description |
|---|---|---|---|
| GET/POST | `/auth/login` | `login` | Login form; redirects to setup if no admin exists |
| GET | `/auth/logout` | `logout` | Clears session |
| GET/POST | `/auth/setup` | `setup` | First-run admin account creation |
| GET | `/admin/` | `dashboard` | Pipeline counts, overdue jobs, active job feed sorted by priority |
| GET | `/admin/jobs` | `job_list` | Filterable list: status, priority, tech, date range, full-text search |
| GET | `/admin/jobs/<id>` | `job_detail` | Full ticket: device, parts, status history, SMS log |
| GET/POST | `/admin/jobs/new` | `job_new` | Intake form: upserts customer, creates device + job in one transaction |
| POST | `/admin/jobs/<id>/status` | `job_update_status` | State transition with machine validation; auto-SMS on `ready`, auto-coins on `picked_up` |
| POST | `/admin/jobs/<id>/edit` | `job_edit` | Update notes, pricing, promised date, technician; auto-calculates GST+PST |
| GET | `/admin/customers` | `customer_list` | All customers with job/SMS counts |
| GET | `/admin/customers/<id>` | `customer_detail` | Full device and job history for a customer |
| GET | `/admin/technicians` | `technician_list` | Technician roster with active job counts |
| POST | `/admin/technicians/new` | `technician_new` | Add a technician |
| POST | `/admin/technicians/<id>/toggle` | `technician_toggle` | Activate/deactivate |
| POST | `/admin/jobs/<id>/parts/add` | `part_add` | Add a part to a job |
| POST | `/admin/parts/<id>/status` | `part_update_status` | Update part lifecycle status |
| GET | `/admin/sms-log` | `sms_log` | Global SMS log (last 200) |
| GET | `/admin/invoices` | `invoice_list` | All invoices |
| GET/POST | `/admin/jobs/<id>/invoice/new` | `invoice_new` | Create an invoice from a job, optionally applying coins |
| GET | `/admin/invoices/<id>` | `invoice_detail` | Invoice detail |
| POST | `/admin/invoices/<id>/mark-paid` | `invoice_mark_paid` | Mark invoice paid |
| POST | `/admin/invoices/<id>/send-sms` | `invoice_send_sms` | SMS the invoice amount to the customer |
| GET | `/admin/wallets` | `wallet_list` | All customer wallets by balance |
| GET | `/admin/wallets/<customer_id>` | `wallet_detail` | Wallet + transaction ledger for a customer |
| POST | `/admin/wallets/<customer_id>/adjust` | `wallet_adjust` | Manual credit/debit with a reason |

Root `/` redirects based on login state (defined in `app/__init__.py`).

---

## Key Business Logic

### Tax Calculation (`app/admin/routes.py: _calc_tax`)
BC tax is applied to `labour_cents + parts_cents`:
- **GST = 5%**, **PST = 7%**, stored separately as `gst_cents` / `pst_cents`
- `repair_jobs.total_cents` is a SQLite GENERATED column: `labour + parts + gst + pst`
- Tax is recalculated server-side on every `job_edit` — never trust the client

### State Machine (`ALLOWED_TRANSITIONS`)
A dict maps each status to the set of valid next statuses. The transition guard in `job_update_status` returns 422 with a descriptive message if the move is blocked.

### Customer Upsert
At intake, the customer is looked up by phone number (E.164). If found, their name and email are updated. This means phone is the stable customer identity — a returning customer re-using the same number gets their history linked automatically.

### Phone Validation
`_validate_phone()` enforces Canadian E.164 format (`+1[2-9]\d{9}`) via regex. Invalid phones abort intake with a 400 validation error.

### Crucible Coin Loyalty Wallet (`app/services/wallet.py`)
- 1 coin = $1 CAD (`COIN_VALUE_CENTS = 100`).
- **Earn**: 5 flat coins + 1 coin per $10 of `total_cents`, awarded automatically when a job reaches `picked_up` (`reward_job_pickup`).
- **Redeem**: whole coins only, capped at 25% of the invoice subtotal (`calc_max_coins`). Applied at invoice creation (`invoice_new`), which calls `spend_coins`.
- **Manual adjustment**: admins can credit/debit coins from `/admin/wallets/<id>/adjust` with a required reason; every change writes an append-only row to `wallet_transactions`.
- `spend_coins` raises `ValueError` on insufficient balance — callers must catch it.

### Invoicing (`invoices` table)
An invoice snapshots a job's `labour_cents` / `parts_cents` / `gst_cents` / `pst_cents` at creation time (so later edits to the job don't retroactively change a finalized invoice). `subtotal_cents` and `amount_due_cents` are GENERATED columns; `discount_cents = coins_applied * COIN_VALUE_CENTS`.

### Login Lockout (`app/services/auth.py`)
- `MAX_FAILED_LOGIN_ATTEMPTS = 5`, `LOCKOUT_MINUTES = 15` — per-account, tracked via `admins.failed_attempts` / `admins.locked_until`.
- A failed login increments the counter; hitting the threshold sets `locked_until` and resets the counter. A successful login clears both.
- `locked_until` is an ISO-8601 UTC string compared lexicographically against `now` — same convention as other timestamp columns in this codebase, no datetime parsing needed.
- This is account-level only, not IP-based — an attacker who doesn't know a valid username isn't throttled (there's no row to increment).

### Role Separation (`app/services/auth.py`, `app/admin/routes.py`)
- `admins.role` is `'admin'` (full access) or `'technician'` (jobs assigned to them only). `admins.technician_id` links a technician-role account to its `technicians` row; it's `NULL` for admins and `UNIQUE` (one login per technician).
- `@admin_required` (in `app/services/auth.py`) gates anything outside "view/update jobs assigned to me": customers, other technicians' accounts, SMS log, invoices, wallets, job intake.
- `_can_access_job()` (in `app/admin/routes.py`) is the ownership check for job-scoped routes (`job_detail`, `job_update_status`, `job_edit`, `part_add`, `part_update_status`): admins always pass; technicians pass only if `repair_jobs.technician_id` matches their own.
- `job_list` force-overrides any submitted `tech_id` filter for technician-role sessions (fails closed to `-1`, matching no job, if a technician session somehow has no linked `technician_id`) — the client's filter selection can't be used to browse other technicians' jobs.
- The bootstrap account created via `/auth/setup` is always `role='admin'`. Additional technician logins are created by an existing admin from `/admin/technicians` → "Create Login".
- Session carries `admin_role` and `admin_technician_id` alongside `admin_id`/`admin_username`, set at login/setup — routes check these rather than re-querying the DB every request.

### Public Job Tracking (`app/track/routes.py`)
- Requires **both** the customer's phone number and their ticket number (`repair_jobs.id`) — a phone number alone can't be used to browse someone's repair history.
- Shows status, device make/model, promised date, and quoted estimate; deliberately omits passcode, internal notes, and full pricing/technician detail.
- Not rate-limited — two-factor lookup (phone + ticket) is the only protection against enumeration.

### SMS Service (`app/services/sms_service.py`)
- Currently a **stub** — POSTs to a placeholder URL, not a real provider.
- `INVOICETOSMS_API_KEY` env var must be set for real sending (currently goes to a placeholder endpoint).
- Every attempt is written to `sms_log` regardless of success/failure.
- Auto-sent: `sms_intake` (job creation), `sms_ready` (status → ready). Manually triggerable: invoice amount-due SMS (`invoice_send_sms`).
- **TODO:** replace provider URL and test with real credentials before production.

---

## Code Conventions

- **Blueprint pattern** — admin routes in `app/admin/routes.py` on `admin_bp`; auth routes in `app/auth/routes.py` on `auth_bp`; both registered in `create_app()`.
- **`get_db()` via Flask `g`** — one connection per request, closed by `teardown_appcontext`.
- **`sqlite3.Row`** — rows addressable by column name. Use `dict(row)` when passing to templates or JSON.
- **Integer cents throughout** — never store or pass float dollars for monetary values. Format for display in templates only.
- **Explicit transactions** — routes that write use `db.execute("BEGIN")` / `db.commit()` / `db.execute("ROLLBACK")` explicitly. Don't rely on sqlite3's autocommit.
- **Catch `sqlite3.IntegrityError` on writes that can conflict** (e.g. duplicate technician email, invalid FK) and turn it into a friendly flash/error response — don't let it bubble into a raw 500. See `technician_new`, `job_new`, `job_edit` in `app/admin/routes.py` for the pattern.
- **Dual HTML/JSON** — most read routes check `_wants_json()` and can return JSON. Useful for future API consumers or AJAX.
- **CSRF token required on every POST form** — see the CSRF Protection section above.
- **Auth required** — every `admin_bp` route is behind `@login_required`. `auth_bp` routes (`login`, `setup`) are intentionally open.
- **Tests** — run `python -m pytest` before committing route/service changes; see the Testing section above.
- **Schema in SQL file** — `db/schema.sql` is the source of truth, not inline Python strings.

---

## Adding New Features

### Adding a route
1. Add the function to `app/admin/routes.py` (or `app/auth/routes.py`) decorated with `@admin_bp.route(...)` / `@auth_bp.route(...)`.
2. Decorate admin routes with `@login_required`.
3. Add a template in `app/templates/admin/` (or `app/templates/auth/`) if needed.
4. If the route handles a POST/PUT/PATCH/DELETE form, add `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` inside the `<form>` — the app-wide `before_request` hook will 400 otherwise.
5. Wire navigation in `app/templates/base.html`.

### Adding a DB table
1. Add `CREATE TABLE IF NOT EXISTS ...` to `db/schema.sql`.
2. Run `flask --app app init-db` — **this wipes and recreates all tables**.
3. For non-destructive changes on an existing DB, run `ALTER TABLE` manually in SQLite.

### Adding a new SMS trigger
1. Add a convenience function to `app/services/sms_service.py` following the `sms_intake` / `sms_ready` pattern.
2. Call it from the relevant route after committing the DB transaction (the SMS function does its own `db.commit()` for the `sms_log` row).

---

## Relationship to `invoicetosms`

This repo is the v2 rewrite. Key upgrades over the v1:

| Area | `invoicetosms` (v1) | `the-crucible` (v2) |
|---|---|---|
| Routes | All in `app.py` flat factory | Blueprints (`/admin`, `/auth`) |
| Schema source | Python string in `database.py` | `db/schema.sql` |
| Job states | 8 states, free transition | 10 states, state machine guard |
| Devices | Embedded in repair_jobs | Separate `devices` table |
| Money | Float (REAL) | Integer cents |
| Tax columns | Single `TAX_RATE` constant | Separate `gst_cents` / `pst_cents` |
| Technicians | None | `technicians` table, assignable |
| Parts | None | `parts` table with lifecycle |
| SMS provider | Twilio | invoicetosms.com stub (TODO) |
| Auth | Salted SHA-256 admin login | Session login, werkzeug PBKDF2 hashing, CSRF-protected forms |
| Loyalty coins | Full wallet system | Ported: `wallets` / `wallet_transactions`, earn-on-pickup, redeem-on-invoice |
| Invoicing | Ported from v1 | `invoices` table, snapshots job pricing, coin discounts |
| Customer self-serve tracking | `/track` route | Not ported yet |
| Customer self-serve tracking | `/track` route | Ported: public phone + ticket lookup, no login |
| Account tiers | Admin only | `admin` and `technician` roles; technicians scoped to their own jobs |

---

## Known TODOs (from codebase)

- **Real SMS provider** — `sms_service.py` points at a placeholder URL; wire up real credentials via `INVOICETOSMS_API_KEY`.
- **Customer self-serve tracking** — the v1 `/track` route (public job-status lookup) has not been ported.
- **Single account tier** — no per-technician logins or role separation; every admin account has full access.
- **No login rate limiting** — `/auth/login` has no lockout/throttle on repeated failed attempts.
- **CI** — the pytest suite exists (`tests/`) but nothing runs it automatically yet; no GitHub Actions workflow.

## CI

`.github/workflows/tests.yml` runs the pytest suite on every push and pull request against `main` (ubuntu-latest, Python 3.12).

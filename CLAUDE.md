# CLAUDE.md — The Crucible (v2 Backend)

## Project Overview

**The Crucible** is a Flask web application for managing a tech repair shop. This repository is the v2 rewrite of the `invoicetosms` repo — it uses a proper Blueprint architecture, a stricter 10-state job lifecycle with a validated state machine, a separate `devices` entity, per-job parts tracking, technician assignment, and all money stored as integer cents.

The `feature/initial-crucible-backend` branch is where all active development lives. `main` contains only the initial GitHub-generated commit.

---

## Architecture

```
the-crucible/
├── run.py                  # Dev entry point: python run.py
├── serve.py                # cwd-agnostic entry point for preview tools / IDE launch
├── app/
│   ├── __init__.py         # Flask app factory (create_app)
│   ├── db.py               # SQLite helpers: get_db, close_db, init_db, flask init-db CLI
│   ├── admin/
│   │   ├── __init__.py     # Blueprint: admin_bp, url_prefix="/admin"
│   │   └── routes.py       # All 7 admin routes + helpers
│   ├── services/
│   │   └── sms_service.py  # SMS stub: send_sms, sms_intake, sms_ready
│   └── templates/
│       ├── base.html
│       └── admin/
│           ├── dashboard.html
│           ├── job_list.html
│           ├── job_detail.html
│           ├── job_new.html
│           └── customer_detail.html
├── db/
│   └── schema.sql          # Full SQLite schema (7 tables, indexes, trigger)
├── .claude/
│   └── launch.json         # Claude Code preview: python run.py on port 5000
├── requirements.txt        # flask>=3.0,<4.0 (cryptography commented out — TODO)
└── .gitignore
```

---

## Tech Stack

- **Python 3.12 / Flask 3.x** — app factory + Blueprint pattern
- **SQLite 3.35+** — raw `sqlite3`, no ORM; uses GENERATED columns and WAL mode
- **stdlib `urllib.request`** — SMS HTTP stub (no extra dependencies yet)
- **Jinja2** — templating (built into Flask)

No Twilio dependency. SMS is currently a stub that POSTs to a placeholder `invoicetosms.com` URL. The real provider and API key aren't wired up yet.

---

## Database Schema

The schema lives in `db/schema.sql` and is applied via `flask init-db` (or `init_db()` in code). It uses `CREATE TABLE IF NOT EXISTS` — **running init-db drops and recreates all tables** (see `init_db()` in `app/db.py`).

| Table | Purpose |
|---|---|
| `technicians` | Staff who perform repairs |
| `customers` | Name, phone (E.164, unique), email |
| `devices` | One device per repair; FK to customer |
| `repair_jobs` | Core table — device + customer + tech + lifecycle state + pricing |
| `job_status_history` | Append-only audit log of every status transition |
| `parts` | Parts ordered/installed per job |
| `sms_log` | Every SMS attempt: queued/sent/delivered/failed |

**Key design decisions:**
- **Phone is the customer upsert key** — `customers.phone` is UNIQUE; intake updates name/email if phone already exists.
- **Money is stored as integer cents** — avoids floating-point drift; all `*_cents` columns. `total_cents` is a `GENERATED ALWAYS AS` column (labour + parts + gst + pst).
- **WAL mode** — `PRAGMA journal_mode = WAL` is set on every connection in `get_db()`.
- **Device passcode** is stored in plaintext — there is a `TODO` comment to encrypt it with Fernet before production. The `cryptography` package is in `requirements.txt` but commented out.

---

## Job Lifecycle (10 states)

```
received → diagnosed → awaiting_parts → in_repair → quality_check → ready → picked_up
                     ↘ cancelled ↗                                   ↓
                                                               warranty_return → in_repair
                                                                              → closed
```

State transitions are **strictly enforced** by `ALLOWED_TRANSITIONS` in `routes.py`. The route returns HTTP 422 if an illegal move is attempted. `closed` is a terminal state with no exits.

**SMS auto-fires** on two transitions:
- `received` (intake): `sms_intake()` sent immediately after job creation
- `→ ready`: `sms_ready()` sent when status moves to `ready`

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes (prod) | Flask session secret; defaults to `"dev-change-in-production"` |
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

`/` redirects to `/admin/`. There's no login screen yet — authentication is not implemented.

**Alternative entry points:**
- `python serve.py` — cwd-agnostic, safe to launch from any directory
- `gunicorn "app:create_app()" --bind 0.0.0.0:8000` — production

**Claude Code preview:** `.claude/launch.json` is configured to run `python run.py` on port 5000.

---

## Route Map

All routes are on the `admin_bp` Blueprint (prefix `/admin`). Routes respond to `Accept: application/json` for JSON output — the `_wants_json()` helper selects response type.

| Method | Route | Function | Description |
|---|---|---|---|
| GET | `/admin/` | `dashboard` | Pipeline counts, overdue jobs, active job feed sorted by priority |
| GET | `/admin/jobs` | `job_list` | Filterable list: status, priority, tech, date range, full-text search |
| GET | `/admin/jobs/<id>` | `job_detail` | Full ticket: device, parts, status history, SMS log |
| GET/POST | `/admin/jobs/new` | `job_new` | Intake form: upserts customer, creates device + job in one transaction |
| POST | `/admin/jobs/<id>/status` | `job_update_status` | State transition with machine validation; auto-SMS on `ready` |
| POST | `/admin/jobs/<id>/edit` | `job_edit` | Update notes, pricing, promised date; auto-calculates GST+PST |
| GET | `/admin/customers/<id>` | `customer_detail` | Full device and job history for a customer |

Root `/` redirects to `/admin/` (defined in `app/__init__.py`).

---

## Key Business Logic

### Tax Calculation (`routes.py: _calc_tax`)
BC tax is applied to `labour_cents + parts_cents`:
- **GST = 5%**, **PST = 7%**, stored separately as `gst_cents` / `pst_cents`
- `total_cents` is a SQLite GENERATED column: `labour + parts + gst + pst`
- Tax is recalculated server-side on every `job_edit` — never trust the client

### State Machine (`ALLOWED_TRANSITIONS`)
A dict maps each status to the set of valid next statuses. The transition guard in `job_update_status` returns 422 with a descriptive message if the move is blocked. This is stricter than the v1 (`invoicetosms`) which allowed any status to be set freely.

### Customer Upsert
At intake, the customer is looked up by phone number (E.164). If found, their name and email are updated. This means phone is the stable customer identity — a returning customer re-using the same number gets their history linked automatically.

### Phone Validation
`_validate_phone()` enforces Canadian E.164 format (`+1[2-9]\d{9}`) via regex. Invalid phones abort intake with a 400 validation error.

### SMS Service (`app/services/sms_service.py`)
- Currently a **stub** — POSTs to a placeholder URL, not a real provider.
- `INVOICETOSMS_API_KEY` env var must be set for real sending (currently goes to a placeholder endpoint).
- Every attempt is written to `sms_log` regardless of success/failure.
- Only two messages are sent automatically: `sms_intake` (job creation) and `sms_ready` (status → ready).
- **TODO:** replace provider URL and test with real credentials before production.

---

## Code Conventions

- **Blueprint pattern** — all admin routes in `app/admin/routes.py` on `admin_bp`; registered in `create_app()`.
- **`get_db()` via Flask `g`** — one connection per request, closed by `teardown_appcontext`.
- **`sqlite3.Row`** — rows addressable by column name. Use `dict(row)` when passing to templates or JSON.
- **Integer cents throughout** — never store or pass float dollars for monetary values. Format for display in templates only.
- **Explicit transactions** — routes that write use `db.execute("BEGIN")` / `db.commit()` / `db.execute("ROLLBACK")` explicitly. Don't rely on sqlite3's autocommit.
- **Dual HTML/JSON** — every read route checks `_wants_json()` and can return JSON. Useful for future API consumers or AJAX.
- **No auth yet** — there is no login system. All `/admin/*` routes are open. This must be added before exposing the app publicly.
- **No test suite** — no automated tests exist.
- **Schema in SQL file** — `db/schema.sql` is the source of truth, not inline Python strings.

---

## Adding New Features

### Adding a route
1. Add the function to `app/admin/routes.py` decorated with `@admin_bp.route(...)`.
2. Add a template in `app/templates/admin/` if needed.
3. Wire navigation in `app/templates/base.html`.

### Adding a DB table
1. Add `CREATE TABLE IF NOT EXISTS ...` to `db/schema.sql`.
2. Run `flask --app app init-db` — **this wipes and recreates all tables**.
3. For non-destructive changes on an existing DB, run `ALTER TABLE` manually in SQLite.

### Adding a new SMS trigger
1. Add a convenience function to `app/services/sms_service.py` following the `sms_intake` / `sms_ready` pattern.
2. Call it from the relevant route after committing the DB transaction (the SMS function does its own `db.commit()` for the `sms_log` row).

### Adding authentication
No auth exists yet. The standard approach for this stack:
- Add an `admins` table (see `invoicetosms` repo for reference implementation).
- Add login/logout/setup routes — either on a new Blueprint or directly in `create_app()`.
- Add a `login_required` decorator and apply it to `admin_bp` routes.

---

## Relationship to `invoicetosms`

This repo is the v2 rewrite. Key upgrades over the v1:

| Area | `invoicetosms` (v1) | `the-crucible` (v2) |
|---|---|---|
| Routes | All in `app.py` flat factory | Blueprint (`/admin`) |
| Schema source | Python string in `database.py` | `db/schema.sql` |
| Job states | 8 states, free transition | 10 states, state machine guard |
| Devices | Embedded in repair_jobs | Separate `devices` table |
| Money | Float (REAL) | Integer cents |
| Tax columns | Single `TAX_RATE` constant | Separate `gst_cents` / `pst_cents` |
| Technicians | None | `technicians` table, assignable |
| Parts | None | `parts` table with lifecycle |
| SMS provider | Twilio | invoicetosms.com stub (TODO) |
| Auth | Salted SHA-256 admin login | Not implemented yet |
| Loyalty coins | Full wallet system | Not ported yet |
| DB init | Auto on startup | `flask init-db` CLI |

---

## Known TODOs (from codebase)

- **Passcode encryption** — `devices.passcode` stored in plaintext; encrypt with Fernet (`cryptography` package, already in requirements but commented out).
- **Real SMS provider** — `sms_service.py` points at a placeholder URL; wire up real credentials via `INVOICETOSMS_API_KEY`.
- **Authentication** — no login system; all admin routes are open.
- **Loyalty/coin system** — not ported from v1.
- **Invoicing** — not ported from v1.
- **Customer self-serve tracking** — not ported from v1 (`/track` route).

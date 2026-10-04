# The Crucible — Mobile API Contract (v1)

Base URL: `https://<host>/api/v1`
Content type: `application/json` for all request bodies and responses.
All money values are **integer cents** (e.g. `11200` = $112.00 CAD).
Timestamps are ISO-8601 UTC strings (e.g. `2026-10-04T07:30:00.000Z`).
Dates (`promised_date`) are `YYYY-MM-DD` strings.

## Authentication

Every endpoint except `GET /health` and `POST /auth/login` requires:

```
Authorization: Bearer <token>
```

Tokens are opaque strings issued by `POST /auth/login`. Only the SHA-256
hash is stored server-side; the raw token is shown once at login and never
again. Two account types exist (the web app has two separate login systems):

| `account_type` | Logs in with                  | Can access                        |
|----------------|-------------------------------|-----------------------------------|
| `staff`        | `username` + `password`        | `/dashboard`, `/jobs*`, `/invoices*`, `/customers*` |
| `customer`     | `phone` + `password`          | `/portal/timeline` only           |

Staff tokens carry a `role`: `admin` (full access) or `technician` (only
jobs assigned to their own technician record — every other job 403s).
Technicians cannot touch invoices, customers, the dashboard, or job intake.

## Errors

All errors use one shape, with an appropriate HTTP status:

```json
{
  "error": {
    "code": "invalid_transition",
    "message": "Transition 'diagnosed' → 'closed' is not permitted. Allowed next states: ['awaiting_parts', 'cancelled', 'in_repair']."
  }
}
```

| HTTP | `code`                | Meaning                                              |
|------|-----------------------|------------------------------------------------------|
| 400  | `validation_error`    | Bad field value / missing required field             |
| 401  | `unauthorized`        | Missing, malformed, invalid, or revoked token        |
| 401  | `invalid_credentials` | Wrong username/phone or password on login            |
| 403  | `forbidden`           | Valid token, but wrong account type/role for this endpoint, or a technician accessing someone else's job |
| 404  | `not_found`           | Unknown id or unknown `/api/v1/*` path               |
| 405  | `method_not_allowed`  | Wrong HTTP method for the path                       |
| 409  | `conflict`            | Duplicate unique value (e.g. customer phone)         |
| 422  | `invalid_transition`  | Job status change the state machine forbids          |
| 423  | `account_locked`      | Too many failed logins; try again after 15 minutes   |
| 429  | `rate_limited`        | Too many requests; back off and retry                |

## Pagination

List endpoints accept `?page=` (default `1`) and `?per_page=` (default `20`,
max `100`) and return:

```json
{
  "data": [ ... ],
  "page": 2,
  "per_page": 10,
  "total": 25
}
```

---

## Endpoints

### `GET /health` — no auth

```json
{ "ok": true, "version": "1" }
```

### `POST /auth/login` — no auth (rate-limited: 10/min per IP)

Staff login **or** customer login — send exactly one of `username` / `phone`.

Request (staff):
```json
{ "username": "domsadmin", "password": "secret123", "device_name": "Pixel 8" }
```
Request (customer):
```json
{ "phone": "+16045550101", "password": "secret123", "device_name": "Pixel 8" }
```
`device_name` is optional — it's just a label shown nowhere critical.

Response `200` (staff):
```json
{
  "token": "<opaque-token-show-once>",
  "account_type": "staff",
  "role": "admin",
  "username": "domsadmin"
}
```
Response `200` (customer):
```json
{
  "token": "<opaque-token-show-once>",
  "account_type": "customer",
  "customer_id": 7,
  "name": "Jane Doe"
}
```
Errors: `400 validation_error` (neither/both of username+phone given),
`401 invalid_credentials`, `423 account_locked`.

### `POST /auth/logout` — auth: any token

Revokes the calling token. Response `200`:
```json
{ "success": true }
```

### `GET /dashboard` — auth: staff + `role=admin`

Revenue overview, job status counts, 10 most recent jobs.

Response `200`:
```json
{
  "revenue": {
    "collected_cents": 11200,
    "month_cents": 3400,
    "outstanding_cents": 5600,
    "unpaid_count": 2
  },
  "status_counts": { "received": 3, "in_repair": 1, "ready": 2 },
  "recent_jobs": [ { "<job brief>" }, ... ]
}
```
Errors: `403 forbidden` for technicians and customers.

### `GET /jobs` — auth: staff (technicians auto-scoped to own jobs)

Query params: `status`, `priority`, `search`, `tech_id` (admins only —
technicians always see only their own jobs regardless), `page`, `per_page`.

Response `200`: paginated list of **job briefs**:
```json
{
  "data": [
    {
      "id": 12,
      "status": "in_repair",
      "priority": "high",
      "created_at": "2026-10-03T18:22:10.000Z",
      "promised_date": "2026-10-06",
      "total_cents": 13440,
      "customer": { "id": 7, "name": "Jane Doe", "phone": "+16045550101" },
      "device": { "make": "Apple", "model": "iPhone 14" },
      "technician": { "id": 2, "name": "Tech One" }
    }
  ],
  "page": 1, "per_page": 20, "total": 1
}
```
`technician` is `null` when unassigned.

### `POST /jobs` — auth: staff + `role=admin`

Intake: upserts the customer by phone, creates device + job, seeds status
history, fires the intake SMS. Mirrors the web intake form.

Request:
```json
{
  "customer_name": "Jane Doe",
  "customer_phone": "+16045550101",
  "customer_email": "jane@example.com",
  "device_make": "Apple",
  "device_model": "iPhone 14",
  "device_serial": "356938035643809",
  "device_passcode": "1234",
  "device_condition": "cracked back glass",
  "description": "Screen replacement",
  "priority": "normal",
  "technician_id": 2,
  "promised_date": "2026-10-08",
  "quoted_cents": 15000
}
```
Required: `customer_name`, `customer_phone` (Canadian E.164, `+1XXXXXXXXXX`),
`device_make`, `device_model`. `priority` is one of
`low|normal|high|urgent` (default `normal`).

Response `201`:
```json
{
  "job_id": 13,
  "job": { "<full job object, see GET /jobs/{id}>" },
  "sms": { "success": false, "error_message": "..." }
}
```
Errors: `400 validation_error`, `403 forbidden` (technicians),
`409 conflict` (data conflict).

### `GET /jobs/{id}` — auth: staff (technicians: own jobs only)

Response `200` — **full job object**:
```json
{
  "id": 12,
  "status": "in_repair",
  "priority": "high",
  "description": "Screen replacement",
  "diagnosis_notes": "OLED panel dead",
  "quoted_cents": 15000,
  "deposit_cents": 0,
  "labour_cents": 10000,
  "parts_cents": 2000,
  "gst_cents": 600,
  "pst_cents": 840,
  "total_cents": 13440,
  "promised_date": "2026-10-08",
  "created_at": "2026-10-03T18:22:10.000Z",
  "updated_at": "2026-10-04T07:30:00.000Z",
  "customer": { "id": 7, "name": "Jane Doe", "phone": "+16045550101", "email": "jane@example.com" },
  "device": { "id": 5, "make": "Apple", "model": "iPhone 14", "serial_imei": "356938035643809", "condition_notes": "cracked back glass" },
  "technician": { "id": 2, "name": "Tech One" },
  "history": [
    { "old_status": null, "new_status": "received", "changed_by": "intake", "note": "Job created via API.", "changed_at": "2026-10-03T18:22:10.000Z" },
    { "old_status": "received", "new_status": "diagnosed", "changed_by": "domsadmin", "note": "Checked it", "changed_at": "2026-10-04T07:30:00.000Z" }
  ]
}
```
The device passcode is never exposed. Errors: `403 forbidden` (technician,
other tech's job), `404 not_found`.

### `PATCH /jobs/{id}` — auth: staff (technicians: own jobs only)

Partial update. `status` goes through the 10-state machine — illegal moves
return `422 invalid_transition` and are listed in the message. A status
change writes a `job_status_history` row; `ready` fires the customer SMS;
`picked_up` awards Crucible Coins. Changing `labour_cents`/`parts_cents`
recalculates GST (5%) + PST (7%) server-side. Only admins may change
`technician_id`.

Request (all fields optional):
```json
{
  "status": "diagnosed",
  "note": "OLED confirmed dead",
  "priority": "urgent",
  "description": "...",
  "diagnosis_notes": "...",
  "promised_date": "2026-10-09",
  "labour_cents": 10000,
  "parts_cents": 2500,
  "deposit_cents": 5000,
  "technician_id": 3
}
```
Response `200`: the full job object (same shape as `GET /jobs/{id}`).
Errors: `400 validation_error`, `403 forbidden`, `404 not_found`,
`409 conflict`, `422 invalid_transition`.

Valid statuses: `received, diagnosed, awaiting_parts, in_repair,
quality_check, ready, picked_up, cancelled, warranty_return, closed`.

### `GET /invoices` — auth: staff + `role=admin`

Paginated (`page`, `per_page`). Response `200`:
```json
{
  "data": [
    {
      "id": 4,
      "job_id": 12,
      "customer_id": 7,
      "customer_name": "Jane Doe",
      "labour_cents": 10000,
      "parts_cents": 2000,
      "gst_cents": 600,
      "pst_cents": 840,
      "subtotal_cents": 13440,
      "coins_applied": 5,
      "discount_cents": 500,
      "amount_due_cents": 12940,
      "status": "unpaid",
      "paid_at": null,
      "notes": null,
      "created_at": "2026-10-04T08:00:00.000Z"
    }
  ],
  "page": 1, "per_page": 20, "total": 1
}
```

### `POST /invoices` — auth: staff + `role=admin`

Creates an invoice snapshotting the job's current pricing. `coins_applied`
is capped at 25% of the subtotal (server returns the max in the error).

Request:
```json
{ "job_id": 12, "coins_applied": 5, "notes": "Paid half cash" }
```
Response `201`: the invoice object (same shape as above).
Errors: `400 validation_error` (unknown job shape, bad coins),
`404 not_found` (job id), `409 conflict`.

### `GET /invoices/{id}` — auth: staff + `role=admin`

Response `200`: the invoice object. Errors: `404 not_found`.

### `GET /customers` — auth: staff + `role=admin`

Query params: `search` (name/phone/email), `page`, `per_page`.
Response `200`: paginated list of:
```json
{ "id": 7, "name": "Jane Doe", "phone": "+16045550101", "email": "jane@example.com", "created_at": "2026-10-03T18:20:00.000Z" }
```

### `POST /customers` — auth: staff + `role=admin`

Request:
```json
{ "name": "Jane Doe", "phone": "+16045550101", "email": "jane@example.com" }
```
`name` and `phone` (Canadian E.164) required. Response `201`: the customer
object. Errors: `400 validation_error`, `409 conflict` (phone already exists).

### `GET /customers/{id}` — auth: staff + `role=admin`

Response `200`: the customer object. Errors: `404 not_found`.

### `GET /portal/timeline` — auth: customer token only

The logged-in customer's own jobs, each with its full status history
(oldest first). Never includes other customers' jobs.

Response `200`:
```json
{
  "jobs": [
    {
      "id": 12,
      "status": "in_repair",
      "priority": "high",
      "created_at": "2026-10-03T18:22:10.000Z",
      "promised_date": "2026-10-08",
      "total_cents": 13440,
      "device": { "make": "Apple", "model": "iPhone 14" },
      "history": [
        { "old_status": null, "new_status": "received", "changed_by": "intake", "note": "...", "changed_at": "2026-10-03T18:22:10.000Z" }
      ]
    }
  ],
  "count": 1
}
```
Errors: `403 forbidden` (staff tokens).

---

## Notes for the mobile client

- Store the token in the platform secure storage (Android Keystore /
  iOS Keychain). It is shown once at login — if lost, log in again.
- Send `Authorization: Bearer <token>` on every call except `/health`
  and `/auth/login`. On `401 unauthorized`, drop the token and show login.
- `423 account_locked` means the account is temporarily locked after 5
  failed logins — show a "try again in 15 minutes" message, don't retry.
- Money is always integer cents; divide by 100 for display.
- Job status values are lowercase snake_case; the timeline `history`
  array is the source of truth for the repair-progress UI.

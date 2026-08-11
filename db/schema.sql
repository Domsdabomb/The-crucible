-- The Crucible — Tech Repair Shop DB Schema
-- SQLite 3.35+  (supports GENERATED columns)
-- Run via:  sqlite3 crucible.db < db/schema.sql

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ─────────────────────────────────────────────
-- 1. TECHNICIANS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS technicians (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    email       TEXT    UNIQUE,
    phone       TEXT,                          -- E.164
    active      INTEGER NOT NULL DEFAULT 1     -- BOOL: 0/1
                CHECK (active IN (0, 1)),
    created_at  TEXT    NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ─────────────────────────────────────────────
-- 2. CUSTOMERS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS customers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    phone       TEXT    NOT NULL UNIQUE,       -- E.164, used for SMS & upsert key
    email       TEXT,
    created_at  TEXT    NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers (phone);

-- ─────────────────────────────────────────────
-- 3. DEVICES
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS devices (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id      INTEGER NOT NULL REFERENCES customers (id) ON DELETE RESTRICT,
    make             TEXT    NOT NULL,
    model            TEXT    NOT NULL,
    serial_imei      TEXT,
    -- Fernet-encrypted (see app/services/crypto.py); never store plaintext here.
    passcode         TEXT,
    condition_notes  TEXT,
    created_at       TEXT    NOT NULL
                     DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_devices_customer ON devices (customer_id);

-- ─────────────────────────────────────────────
-- 4. REPAIR JOBS
-- ─────────────────────────────────────────────
-- 10-state lifecycle:
--   received → diagnosed → awaiting_parts → in_repair → quality_check
--   → ready → picked_up → cancelled → warranty_return → closed
CREATE TABLE IF NOT EXISTS repair_jobs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id        INTEGER NOT NULL REFERENCES devices (id)     ON DELETE RESTRICT,
    customer_id      INTEGER NOT NULL REFERENCES customers (id)   ON DELETE RESTRICT,
    technician_id    INTEGER          REFERENCES technicians (id) ON DELETE SET NULL,

    status           TEXT    NOT NULL DEFAULT 'received'
                     CHECK (status IN (
                         'received', 'diagnosed', 'awaiting_parts', 'in_repair',
                         'quality_check', 'ready', 'picked_up',
                         'cancelled', 'warranty_return', 'closed'
                     )),

    priority         TEXT    NOT NULL DEFAULT 'normal'
                     CHECK (priority IN ('low', 'normal', 'high', 'urgent')),

    description      TEXT,
    diagnosis_notes  TEXT,

    -- All monetary values stored as integer cents to avoid floating-point drift.
    quoted_cents     INTEGER NOT NULL DEFAULT 0 CHECK (quoted_cents  >= 0),
    deposit_cents    INTEGER NOT NULL DEFAULT 0 CHECK (deposit_cents >= 0),
    labour_cents     INTEGER NOT NULL DEFAULT 0 CHECK (labour_cents  >= 0),
    parts_cents      INTEGER NOT NULL DEFAULT 0 CHECK (parts_cents   >= 0),
    -- BC tax rates: GST 5%, PST 7%
    gst_cents        INTEGER NOT NULL DEFAULT 0 CHECK (gst_cents     >= 0),
    pst_cents        INTEGER NOT NULL DEFAULT 0 CHECK (pst_cents     >= 0),
    -- GENERATED: automatically kept in sync by SQLite
    total_cents      INTEGER GENERATED ALWAYS AS
                     (labour_cents + parts_cents + gst_cents + pst_cents) STORED,

    promised_date    TEXT,                     -- ISO-8601 date
    created_at       TEXT    NOT NULL
                     DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at       TEXT    NOT NULL
                     DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_status     ON repair_jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_priority   ON repair_jobs (priority);
CREATE INDEX IF NOT EXISTS idx_jobs_customer   ON repair_jobs (customer_id);
CREATE INDEX IF NOT EXISTS idx_jobs_technician ON repair_jobs (technician_id);

-- Keep updated_at current on every write
CREATE TRIGGER IF NOT EXISTS trg_jobs_updated_at
AFTER UPDATE ON repair_jobs
FOR EACH ROW
BEGIN
    UPDATE repair_jobs
    SET    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE  id = NEW.id;
END;

-- ─────────────────────────────────────────────
-- 5. JOB STATUS HISTORY  (append-only audit log)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS job_status_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER NOT NULL REFERENCES repair_jobs (id) ON DELETE CASCADE,
    old_status  TEXT,                          -- NULL on initial insert
    new_status  TEXT    NOT NULL,
    changed_by  TEXT    NOT NULL,              -- technician name or 'system'
    note        TEXT,
    changed_at  TEXT    NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_history_job ON job_status_history (job_id);

-- ─────────────────────────────────────────────
-- 6. PARTS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS parts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER NOT NULL REFERENCES repair_jobs (id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    part_number TEXT,
    supplier    TEXT,
    cost_cents  INTEGER NOT NULL DEFAULT 0 CHECK (cost_cents >= 0),
    status      TEXT    NOT NULL DEFAULT 'ordered'
                CHECK (status IN ('ordered', 'received', 'installed', 'returned')),
    created_at  TEXT    NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_parts_job ON parts (job_id);

-- ─────────────────────────────────────────────
-- 7. SMS LOG
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sms_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id              INTEGER REFERENCES repair_jobs (id) ON DELETE SET NULL,
    customer_id         INTEGER REFERENCES customers (id)  ON DELETE SET NULL,
    message_body        TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued', 'sent', 'delivered', 'failed')),
    provider_message_id TEXT,
    error_message       TEXT,
    sent_at             TEXT    NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_sms_job      ON sms_log (job_id);
CREATE INDEX IF NOT EXISTS idx_sms_customer ON sms_log (customer_id);

-- ─────────────────────────────────────────────
-- 8. WALLETS  (Crucible Coin loyalty balances)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wallets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id   INTEGER NOT NULL UNIQUE REFERENCES customers (id) ON DELETE CASCADE,
    balance_coins INTEGER NOT NULL DEFAULT 0 CHECK (balance_coins >= 0),
    created_at    TEXT    NOT NULL
                  DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT    NOT NULL
                  DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ─────────────────────────────────────────────
-- 9. WALLET TRANSACTIONS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wallet_transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_id     INTEGER NOT NULL REFERENCES wallets (id) ON DELETE CASCADE,
    type          TEXT    NOT NULL CHECK (type IN ('credit', 'debit')),
    amount_coins  INTEGER NOT NULL CHECK (amount_coins > 0),
    balance_after INTEGER NOT NULL CHECK (balance_after >= 0),
    reason        TEXT    NOT NULL,
    job_id        INTEGER REFERENCES repair_jobs (id) ON DELETE SET NULL,
    created_at    TEXT    NOT NULL
                  DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_wallet_txn_wallet ON wallet_transactions (wallet_id);

-- ─────────────────────────────────────────────
-- 10. INVOICES
-- ─────────────────────────────────────────────
-- Each invoice snaps the job's pricing at creation time.
-- coins_applied × 100 = discount_cents (1 coin = $1 CAD).
CREATE TABLE IF NOT EXISTS invoices (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           INTEGER NOT NULL REFERENCES repair_jobs (id) ON DELETE RESTRICT,
    customer_id      INTEGER NOT NULL REFERENCES customers   (id) ON DELETE RESTRICT,
    labour_cents     INTEGER NOT NULL DEFAULT 0 CHECK (labour_cents  >= 0),
    parts_cents      INTEGER NOT NULL DEFAULT 0 CHECK (parts_cents   >= 0),
    gst_cents        INTEGER NOT NULL DEFAULT 0 CHECK (gst_cents     >= 0),
    pst_cents        INTEGER NOT NULL DEFAULT 0 CHECK (pst_cents     >= 0),
    subtotal_cents   INTEGER GENERATED ALWAYS AS
                     (labour_cents + parts_cents + gst_cents + pst_cents) STORED,
    coins_applied    INTEGER NOT NULL DEFAULT 0 CHECK (coins_applied  >= 0),
    discount_cents   INTEGER NOT NULL DEFAULT 0 CHECK (discount_cents >= 0),
    amount_due_cents INTEGER GENERATED ALWAYS AS
                     (labour_cents + parts_cents + gst_cents + pst_cents - discount_cents) STORED,
    status           TEXT    NOT NULL DEFAULT 'unpaid'
                     CHECK (status IN ('unpaid', 'paid')),
    paid_at          TEXT,
    notes            TEXT,
    created_at       TEXT    NOT NULL
                     DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_invoices_job      ON invoices (job_id);
CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices (customer_id);

-- ─────────────────────────────────────────────
-- 11. ADMINS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admins (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,               -- werkzeug generate_password_hash() (PBKDF2-SHA256)
    created_at    TEXT    NOT NULL
                  DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

"""
Crucible Coin loyalty wallet.

Coin economy:
  1 coin = $1 CAD credit on invoices.
  Earn: 5 coins flat + 1 coin per $10 spent when a job reaches 'picked_up'.
  Redeem: up to 25% of the invoice subtotal, whole coins only.
"""

from app.db import get_db

COIN_VALUE_CENTS = 100          # 1 coin = $1 = 100 cents
COINS_FLAT_ON_PICKUP = 5
COINS_PER_1000_CENTS = 1        # 1 coin per $10 spent
MAX_COIN_DISCOUNT_RATIO = 0.25  # max 25% of subtotal


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def get_or_create_wallet(db, customer_id: int) -> dict:
    row = db.execute(
        "SELECT * FROM wallets WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    if row is None:
        db.execute(
            "INSERT INTO wallets (customer_id) VALUES (?)", (customer_id,)
        )
        row = db.execute(
            "SELECT * FROM wallets WHERE customer_id = ?", (customer_id,)
        ).fetchone()
    return dict(row)


def add_coins(db, customer_id: int, amount: int, reason: str,
              job_id: int | None = None) -> int:
    """Credit coins; returns new balance."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    wallet = get_or_create_wallet(db, customer_id)
    new_balance = wallet["balance_coins"] + amount
    db.execute(
        "UPDATE wallets SET balance_coins = ?, updated_at = ? WHERE id = ?",
        (new_balance, _now_iso(), wallet["id"]),
    )
    db.execute(
        """INSERT INTO wallet_transactions
               (wallet_id, type, amount_coins, balance_after, reason, job_id)
           VALUES (?, 'credit', ?, ?, ?, ?)""",
        (wallet["id"], amount, new_balance, reason, job_id),
    )
    return new_balance


def spend_coins(db, customer_id: int, amount: int, reason: str,
                job_id: int | None = None) -> int:
    """Debit coins; raises ValueError if balance is insufficient. Returns new balance."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    wallet = get_or_create_wallet(db, customer_id)
    if wallet["balance_coins"] < amount:
        raise ValueError(
            f"Insufficient coins: have {wallet['balance_coins']}, need {amount}"
        )
    new_balance = wallet["balance_coins"] - amount
    db.execute(
        "UPDATE wallets SET balance_coins = ?, updated_at = ? WHERE id = ?",
        (new_balance, _now_iso(), wallet["id"]),
    )
    db.execute(
        """INSERT INTO wallet_transactions
               (wallet_id, type, amount_coins, balance_after, reason, job_id)
           VALUES (?, 'debit', ?, ?, ?, ?)""",
        (wallet["id"], amount, new_balance, reason, job_id),
    )
    return new_balance


def calc_max_coins(subtotal_cents: int, balance_coins: int) -> int:
    """Max coins a customer may apply — whole coins, capped at 25% of subtotal."""
    cap_coins = int(subtotal_cents * MAX_COIN_DISCOUNT_RATIO / COIN_VALUE_CENTS)
    return min(balance_coins, cap_coins)


def reward_job_pickup(db, customer_id: int, job_id: int,
                      total_cents: int) -> int:
    """Award coins when a job is picked up. Returns coins awarded."""
    coins = COINS_FLAT_ON_PICKUP + (total_cents // (COINS_PER_1000_CENTS * 1000))
    if coins > 0:
        add_coins(db, customer_id, coins,
                  reason=f"Job #{job_id} completed",
                  job_id=job_id)
    return coins

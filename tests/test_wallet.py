import pytest

from app.services import wallet as wallet_service


def _make_customer(db, phone="+12505550100"):
    cur = db.execute(
        "INSERT INTO customers (name, phone) VALUES (?, ?)", ("Test Customer", phone)
    )
    db.commit()
    return cur.lastrowid


def test_add_coins_credits_balance_and_logs_transaction(db):
    cid = _make_customer(db)
    new_balance = wallet_service.add_coins(db, cid, 10, reason="test credit")
    db.commit()
    assert new_balance == 10

    wallet = wallet_service.get_or_create_wallet(db, cid)
    assert wallet["balance_coins"] == 10

    txns = db.execute(
        "SELECT * FROM wallet_transactions WHERE wallet_id = ?", (wallet["id"],)
    ).fetchall()
    assert len(txns) == 1
    assert txns[0]["type"] == "credit"
    assert txns[0]["balance_after"] == 10


def test_spend_coins_insufficient_balance_raises(db):
    cid = _make_customer(db)
    with pytest.raises(ValueError):
        wallet_service.spend_coins(db, cid, 5, reason="test debit")


def test_spend_coins_success_debits_balance(db):
    cid = _make_customer(db)
    wallet_service.add_coins(db, cid, 10, reason="seed")
    db.commit()
    new_balance = wallet_service.spend_coins(db, cid, 4, reason="redeem")
    db.commit()
    assert new_balance == 6


def test_add_or_spend_zero_or_negative_amount_rejected(db):
    cid = _make_customer(db)
    with pytest.raises(ValueError):
        wallet_service.add_coins(db, cid, 0, reason="noop")
    with pytest.raises(ValueError):
        wallet_service.spend_coins(db, cid, -1, reason="noop")


def test_calc_max_coins_caps_at_25_percent_of_subtotal():
    # $100 subtotal -> 25% cap = 25 coins; balance is well above that
    assert wallet_service.calc_max_coins(subtotal_cents=10000, balance_coins=100) == 25


def test_calc_max_coins_limited_by_balance_when_below_cap():
    assert wallet_service.calc_max_coins(subtotal_cents=10000, balance_coins=5) == 5


def test_reward_job_pickup_formula(db):
    cid = _make_customer(db)
    # 5 flat + 1 coin per $10 of total; $112.00 total -> 5 + 11 = 16
    coins = wallet_service.reward_job_pickup(db, cid, job_id=None, total_cents=11200)
    db.commit()
    assert coins == 16
    wallet = wallet_service.get_or_create_wallet(db, cid)
    assert wallet["balance_coins"] == 16

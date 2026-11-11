"""Spending, income and savings rate. Made-up numbers, checked by hand."""

from datetime import date

import pytest

from app.db.models import Account, AccountKind, DataSource, Transaction
from app.services.spending import CATEGORIES, classify, monthly_summary


@pytest.mark.parametrize(
    "primary, detailed, amount, kind, category",
    [
        ("FOOD_AND_DRINK", "FOOD_AND_DRINK_GROCERIES", -5_000, "spending", "Food"),
        ("RENT_AND_UTILITIES", "RENT_AND_UTILITIES_RENT", -200_000, "spending", "Rent"),
        ("RENT_AND_UTILITIES", "RENT_AND_UTILITIES_INTERNET_AND_CABLE", -6_000, "spending", "Bills & utilities"),
        ("INCOME", "INCOME_WAGES", 300_000, "income", None),
        ("INCOME", "INCOME_RENTAL", 200_000, "spending", "Rent"),
        ("LOAN_PAYMENTS", "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT", -50_000, "transfer", None),
        ("TRANSFER_OUT", None, -10_000, "transfer", None),
        ("MEDICAL", None, -9_000, "spending", "Other"),
        (None, None, -1_000, "spending", "Other"),
        (None, None, 1_000, "transfer", None),
    ],
)
def test_classify(primary, detailed, amount, kind, category):
    c = classify(primary, detailed, amount)
    assert (c.kind, c.category) == (kind, category)


def test_user_category_wins():
    assert classify("FOOD_AND_DRINK", None, -500, "Travel").category == "Travel"
    assert classify("FOOD_AND_DRINK", None, -500, "Transfer").kind == "transfer"


def _add(session, acct, ext, d, cents, primary=None, detailed=None):
    session.add(Transaction(account_id=acct.id, external_id=ext, posted_on=d, amount_cents=cents,
                            description=ext, provider_category=primary, provider_category_detailed=detailed))


def test_month_math_rent_via_card_counts_once(session):
    chk = Account(name="Checking", kind=AccountKind.CHECKING, source=DataSource.MANUAL, external_id="c", balance_cents=0)
    card = Account(name="Card", kind=AccountKind.CREDIT_CARD, source=DataSource.MANUAL, external_id="k", balance_cents=0)
    session.add_all([chk, card])
    session.flush()
    oct_ = date(2026, 10, 3)
    _add(session, chk, "pay1", oct_, 400_000, "INCOME", "INCOME_WAGES")             # +4,000 salary
    # Rent via a rent-rewards card: bank -> card company, card credit, card rent charge
    _add(session, chk, "r1", oct_, -200_000, "RENT_AND_UTILITIES", "RENT_AND_UTILITIES_RENT")
    _add(session, card, "r2", oct_, 200_000, "INCOME", "INCOME_RENTAL")
    _add(session, card, "r3", oct_, -200_000, "RENT_AND_UTILITIES", "RENT_AND_UTILITIES_RENT")
    _add(session, card, "f1", oct_, -30_000, "FOOD_AND_DRINK")                          # 300 food
    _add(session, card, "f2", oct_, 5_000, "FOOD_AND_DRINK")                            # 50 refund
    _add(session, chk, "cc", oct_, -25_000, "LOAN_PAYMENTS", "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT")
    _add(session, card, "ccin", oct_, 25_000, "LOAN_PAYMENTS", "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT")
    session.commit()

    months = monthly_summary(session, months=2, today=date(2026, 11, 5))
    assert [m["month"] for m in months] == ["2026-10", "2026-11"]
    o = months[0]
    # Rent 2,000 once; food 300 − 50 = 250; card payment is a transfer
    assert o["by_category"] == {"Rent": 200_000, "Food": 25_000}
    assert o["spending_cents"] == 225_000 and o["income_cents"] == 400_000
    assert o["saved_cents"] == 175_000 and o["savings_rate"] == 0.4375  # 1,750 / 4,000
    assert o["partial"] is True and o["has_data"] is True  # history starts Oct 3: month incomplete
    n = months[1]
    assert n["spending_cents"] == 0 and n["savings_rate"] is None and n["partial"] is True


def test_categories_are_in_fixed_order():
    assert CATEGORIES[0] == "Rent" and CATEGORIES[-1] == "Other"

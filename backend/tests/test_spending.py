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


# ---- shared expenses (made-up numbers) ----
from app.db.models import SplitExpense  # noqa: E402


def _split(session, d, desc, cost, paid, share, category):
    session.add(SplitExpense(external_id=f"g|{d}|{desc}", spent_on=d, group_name="g", description=desc,
                             cost_cents=cost, you_paid_cents=paid, share_cents=share, category=category))


def test_only_your_share_counts(session):
    chk = Account(name="Checking", kind=AccountKind.CHECKING, source=DataSource.MANUAL, external_id="c", balance_cents=0)
    session.add(chk)
    session.flush()
    _add(session, chk, "rent", date(2026, 11, 2), -200_000, "RENT_AND_UTILITIES", "RENT_AND_UTILITIES_RENT")
    _add(session, chk, "net", date(2026, 10, 13), -6_000, "RENT_AND_UTILITIES")  # internet, logged later
    _add(session, chk, "net-old", date(2026, 9, 13), -6_000, "RENT_AND_UTILITIES")  # same amount, older
    _add(session, chk, "dinner", date(2026, 11, 3), -9_000, "FOOD_AND_DRINK")  # not shared
    _add(session, chk, "zelle", date(2026, 11, 2), 99_000, "TRANSFER_IN")  # housemate repays: not income
    _add(session, chk, "pay", date(2026, 11, 5), 500_000, "INCOME", "INCOME_WAGES")
    # Splitwise: rent 2,000 split in two (you paid); internet 60 (you paid) logged Nov 1;
    # electricity 80 paid by housemate, your share 40; a cab paid by a friend, share 25.
    _split(session, date(2026, 11, 1), "Rent", 200_000, 200_000, 100_000, "Rent")
    _split(session, date(2026, 11, 1), "Internet Oct", 6_000, 6_000, 3_000, "Bills & utilities")
    _split(session, date(2026, 11, 1), "Electricity", 8_000, 0, 4_000, "Bills & utilities")
    _split(session, date(2026, 11, 8), "Cab", 2_500, 0, 2_500, "Transport")
    session.commit()

    m = {x["month"]: x for x in monthly_summary(session, months=3, today=date(2026, 11, 20))}
    # October: internet charge (Oct 13, closest match) counts as your half: 30
    assert m["2026-10"]["by_category"] == {"Bills & utilities": 3_000}
    # September's identical charge is untouched (not shared as far as we know)
    assert m["2026-09"]["by_category"] == {"Bills & utilities": 6_000}
    # November: rent half 1,000 + electricity share 40 + dinner 90 + cab 25
    assert m["2026-11"]["by_category"] == {"Rent": 100_000, "Food": 9_000, "Transport": 2_500,
                                          "Bills & utilities": 4_000}
    assert m["2026-11"]["spending_cents"] == 115_500
    assert m["2026-11"]["income_cents"] == 500_000  # the Zelle repayment isn't income
    assert m["2026-11"]["unmatched_shared"] == 0


def test_paid_but_unmatched_still_counts_share(session):
    _split(session, date(2026, 11, 4), "Concert", 10_000, 10_000, 5_000, "Entertainment")
    session.commit()
    m = monthly_summary(session, months=1, today=date(2026, 11, 20))[0]
    assert m["by_category"] == {"Entertainment": 5_000} and m["unmatched_shared"] == 1


def test_one_charge_matches_only_one_expense(session):
    chk = Account(name="Checking", kind=AccountKind.CHECKING, source=DataSource.MANUAL, external_id="c", balance_cents=0)
    session.add(chk)
    session.flush()
    _add(session, chk, "x", date(2026, 11, 2), -4_000, "FOOD_AND_DRINK")
    _split(session, date(2026, 11, 2), "Lunch A", 4_000, 4_000, 2_000, "Food")
    _split(session, date(2026, 11, 3), "Lunch B", 4_000, 4_000, 2_000, "Food")
    session.commit()
    m = monthly_summary(session, months=1, today=date(2026, 11, 20))[0]
    # A: charge 40 -> share 20. B: no charge left -> share 20 added, flagged unmatched.
    assert m["by_category"] == {"Food": 4_000} and m["unmatched_shared"] == 1

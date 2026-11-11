"""Spending, income and savings rate. Made-up numbers, checked by hand."""

from datetime import date

import pytest

from app.db.models import Account, AccountKind, DataSource, Transaction
from sqlalchemy import select
from app.services.spending import CATEGORIES, classify, monthly_summary


@pytest.mark.parametrize(
    "primary, detailed, amount, kind, category",
    [
        ("FOOD_AND_DRINK", "FOOD_AND_DRINK_GROCERIES", -5_000, "spending", "Food & groceries"),
        ("GENERAL_MERCHANDISE", "GENERAL_MERCHANDISE_SUPERSTORES", -5_000, "spending", "Food & groceries"),
        ("PERSONAL_CARE", None, -3_000, "spending", "Personal care & shopping"),
        ("RENT_AND_UTILITIES", "RENT_AND_UTILITIES_RENT", -200_000, "spending", "Rent"),
        ("RENT_AND_UTILITIES", "RENT_AND_UTILITIES_INTERNET_AND_CABLE", -6_000, "spending", "Bills & subscriptions"),
        ("INCOME", "INCOME_WAGES", 300_000, "income", None),
        ("INCOME", "INCOME_RENTAL", 200_000, "spending", "Rent"),
        ("LOAN_PAYMENTS", "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT", -50_000, "transfer", None),
        ("TRANSFER_OUT", None, -10_000, "transfer", None),
        ("MEDICAL", None, -9_000, "spending", "Health care"),
        ("GENERAL_SERVICES", "GENERAL_SERVICES_AUTOMOTIVE", -2_000, "spending", "Transport & travel"),
        ("GENERAL_SERVICES", "GENERAL_SERVICES_INSURANCE", -9_000, "spending", "Bills & subscriptions"),
        ("GOVERNMENT_AND_NON_PROFIT", None, -500, "spending", "Other"),
        (None, None, -1_000, "spending", "Other"),
        (None, None, 1_000, "transfer", None),
    ],
)
def test_classify(primary, detailed, amount, kind, category):
    c = classify(primary, detailed, amount)
    assert (c.kind, c.category) == (kind, category)


def test_user_category_wins():
    assert classify("FOOD_AND_DRINK", None, -500, "Travel").category == "Transport & travel"
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
    assert o["by_category"] == {"Rent": 200_000, "Food & groceries": 25_000}
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
    assert m["2026-10"]["by_category"] == {"Bills & subscriptions": 3_000}
    # September's identical charge is untouched (not shared as far as we know)
    assert m["2026-09"]["by_category"] == {"Bills & subscriptions": 6_000}
    # November: rent half 1,000 + electricity share 40 + dinner 90 + cab 25
    assert m["2026-11"]["by_category"] == {"Rent": 100_000, "Food & groceries": 9_000, "Transport & travel": 2_500,
                                          "Bills & subscriptions": 4_000}
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
    assert m["by_category"] == {"Food & groceries": 4_000} and m["unmatched_shared"] == 1


def test_rent_base_splits_utilities_out(session, tmp_path):
    import json

    from app import cli

    chk = Account(name="Checking", kind=AccountKind.CHECKING, source=DataSource.MANUAL, external_id="c", balance_cents=0)
    session.add(chk)
    session.flush()
    _add(session, chk, "rent", date(2026, 11, 2), -200_000, "RENT_AND_UTILITIES", "RENT_AND_UTILITIES_RENT")
    session.commit()
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"rent_base": 1800.00, "expenses": [
        {"date": "2026-11-01", "group": "Apt", "description": "Rent", "cost": 2000.00,
         "you_paid": 2000.00, "your_share": 1000.00, "category": "Rent"}]}))
    assert cli.main(["splitwise-import-expenses", str(f)]) == 0
    m = monthly_summary(session, months=1, today=date(2026, 11, 20))[0]
    # your 1,000 share: 1,800/2,000 of it is rent (900), the rest utilities (100)
    assert m["by_category"] == {"Rent": 90_000, "Bills & subscriptions": 10_000}


# ---- household rent rule (made-up: base rent 2,000, your share 1,000) ----
from app.services.spending import RentRule  # noqa: E402

RULE = RentRule(base_cents=200_000, your_share_cents=100_000, people=2)


def _rent_via_card(session, chk, card, d, cents, tag):
    """Rent paid through a rent-rewards card: bank -> card company, card credit, card rent charge."""
    _add(session, chk, f"{tag}1", d, -cents, "RENT_AND_UTILITIES", "RENT_AND_UTILITIES_RENT")
    _add(session, card, f"{tag}2", d, cents, "INCOME", "INCOME_RENTAL")
    _add(session, card, f"{tag}3", d, -cents, "RENT_AND_UTILITIES", "RENT_AND_UTILITIES_RENT")


def _two_accounts(session):
    chk = Account(name="Checking", kind=AccountKind.CHECKING, source=DataSource.MANUAL, external_id="c", balance_cents=0)
    card = Account(name="Card", kind=AccountKind.CREDIT_CARD, source=DataSource.MANUAL, external_id="k", balance_cents=0)
    session.add_all([chk, card])
    session.flush()
    return chk, card


def test_fixed_rent_share_every_month(session):
    chk, card = _two_accounts(session)
    _rent_via_card(session, chk, card, date(2026, 9, 2), 200_000, "sep")    # exactly base rent
    _rent_via_card(session, chk, card, date(2026, 11, 2), 220_000, "nov")   # base + 200 utilities
    _add(session, chk, "oct-food", date(2026, 10, 3), -5_000, "FOOD_AND_DRINK")  # Oct: housemate paid rent
    _add(session, chk, "settle", date(2026, 10, 5), -95_000, "TRANSFER_OUT")     # net settle-up: transfer
    session.commit()
    m = {x["month"]: x for x in monthly_summary(session, months=3, today=date(2026, 11, 20), rent_rule=RULE)}
    assert m["2026-09"]["by_category"] == {"Rent": 100_000}
    assert m["2026-10"]["by_category"] == {"Rent": 100_000, "Food & groceries": 5_000}
    # November: your rent share + half of the 200 utilities billed with rent
    assert m["2026-11"]["by_category"] == {"Rent": 100_000, "Bills & subscriptions": 10_000}


def test_unexplained_extra_is_flagged(session):
    chk, card = _two_accounts(session)
    _rent_via_card(session, chk, card, date(2026, 8, 18), 350_000, "aug")  # 1,500 above base
    session.commit()
    m = monthly_summary(session, months=1, today=date(2026, 8, 25), rent_rule=RULE)[0]
    assert m["by_category"] == {"Rent": 100_000, "Other": 150_000}
    assert m["flags"] == ["rent payment on 2026-08-18 was 1,500.00 above the base rent (unexplained)"]


def test_splitwise_rent_entry_explains_utilities(session):
    chk, card = _two_accounts(session)
    _rent_via_card(session, chk, card, date(2026, 11, 2), 220_000, "nov")
    _split(session, date(2026, 11, 1), "Rent", 220_000, 220_000, 110_000, "Rent")
    session.commit()
    se = session.scalar(select(SplitExpense))
    se.split_parts = '{"Rent": 100000, "Bills & utilities": 10000}'
    session.commit()
    m = monthly_summary(session, months=1, today=date(2026, 11, 20), rent_rule=RULE)[0]
    assert m["by_category"] == {"Rent": 100_000, "Bills & subscriptions": 10_000}  # not counted twice


def test_recategorized_rent_lookalike_moves_out_of_rent(session):
    from app import cli

    chk, card = _two_accounts(session)
    _rent_via_card(session, chk, card, date(2026, 9, 28), 80_000, "fee")  # a school fee paid via the rent portal
    session.commit()
    t = session.scalar(select(Transaction).where(Transaction.external_id == "fee1"))
    assert cli.main(["categorize", str(t.id), "Education", "--note", "Program fee"]) == 0
    session.expire_all()
    m = monthly_summary(session, months=1, today=date(2026, 9, 30), rent_rule=RULE)[0]
    assert m["by_category"] == {"Rent": 100_000, "Education": 80_000}
    assert session.get(Transaction, t.id).note == "Program fee"
    assert cli.main(["categorize", str(t.id), "Nonsense"]) == 1


def test_split_payment_rent_plus_fee(session):
    from app import cli

    chk, card = _two_accounts(session)
    _rent_via_card(session, chk, card, date(2026, 8, 18), 350_000, "aug")  # rent 2,000 + 1,500 fee
    session.commit()
    t = session.scalar(select(Transaction).where(Transaction.external_id == "aug1"))
    assert cli.main(["split-txn", str(t.id), "Rent=2000", "Education=1499"]) == 1  # doesn't add up
    assert cli.main(["split-txn", str(t.id), "Rent=2000", "Education=1500", "--note", "rent + fee"]) == 0
    session.expire_all()  # the command saved through its own session
    m = monthly_summary(session, months=1, today=date(2026, 8, 25), rent_rule=RULE)[0]
    assert m["by_category"] == {"Rent": 100_000, "Education": 150_000} and m["flags"] == []
    # Without the household rule, the split counts as written.
    m2 = monthly_summary(session, months=1, today=date(2026, 8, 25))[0]
    assert m2["by_category"] == {"Rent": 200_000, "Education": 150_000}


def test_old_category_names_are_migrated(session):
    import json

    from app.db.base import engine, init_db

    chk = Account(name="Checking", kind=AccountKind.CHECKING, source=DataSource.MANUAL, external_id="c", balance_cents=0)
    session.add(chk)
    session.flush()
    session.add(Transaction(account_id=chk.id, external_id="t", posted_on=date(2026, 9, 1), amount_cents=-100,
                            description="x", category="Travel",
                            split_parts=json.dumps({"Bills & utilities": 60, "Transport": 40})))
    _split(session, date(2026, 9, 1), "cab", 100, 0, 100, "Transport")
    session.commit()
    init_db(engine)
    session.expire_all()
    t = session.scalar(select(Transaction))
    assert t.category == "Transport & travel"
    assert json.loads(t.split_parts) == {"Bills & subscriptions": 60, "Transport & travel": 40}
    assert session.scalar(select(SplitExpense)).category == "Transport & travel"

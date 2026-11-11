"""Budget year totals. Made-up numbers."""

from datetime import date

from app.db.models import Account, AccountKind, DataSource, Transaction
from app.services.spending import RentRule
from app.services.yearly import deposits_to_review, year_summary

START, END = date(2026, 11, 10), date(2027, 11, 9)
RULE = RentRule(base_cents=200_000, your_share_cents=100_000)


def _setup(session):
    chk = Account(name="Checking", kind=AccountKind.CHECKING, source=DataSource.MANUAL, external_id="c", balance_cents=0)
    session.add(chk)
    session.flush()
    return chk


def _t(session, a, ext, d, cents, primary, detailed=None, desc=None, category=None):
    session.add(Transaction(account_id=a.id, external_id=ext, posted_on=d, amount_cents=cents,
                            description=desc or ext, provider_category=primary,
                            provider_category_detailed=detailed, category=category))


def test_year_totals_and_months(session):
    a = _setup(session)
    _t(session, a, "before", date(2026, 11, 5), -50_000, "FOOD_AND_DRINK")          # before the year
    _t(session, a, "pay1", date(2026, 11, 20), 300_000, "INCOME", "INCOME_SALARY", "PAYROLL")
    _t(session, a, "food1", date(2026, 11, 21), -40_000, "FOOD_AND_DRINK")
    _t(session, a, "inv1", date(2026, 11, 22), -25_000, "TRANSFER_OUT", "TRANSFER_OUT_INVESTMENT_AND_RETIREMENT_FUNDS")
    _t(session, a, "pay2", date(2026, 12, 4), 300_000, "INCOME", "INCOME_SALARY", "PAYROLL")
    _t(session, a, "food2", date(2026, 12, 5), -90_000, "FOOD_AND_DRINK")
    _t(session, a, "inv2", date(2026, 12, 22), -25_000, "TRANSFER_OUT", "TRANSFER_OUT_INVESTMENT_AND_RETIREMENT_FUNDS")
    _t(session, a, "pay3", date(2027, 1, 4), 300_000, "INCOME", "INCOME_SALARY", "PAYROLL")
    _t(session, a, "food3", date(2027, 1, 5), -30_000, "FOOD_AND_DRINK")
    session.commit()
    y = year_summary(session, START, END, today=date(2027, 2, 2), rent_rule=RULE)
    # Rent: December and January (November's rent month started before the year)
    assert y["by_category"] == {"Rent": 200_000, "Food & groceries": 160_000}
    assert (y["income_cents"], y["expenses_cents"]) == (900_000, 360_000)
    assert y["saved_cents"] == 540_000 and y["savings_rate"] == 0.6
    assert y["invested_cents"] == 50_000
    m = {x["month"]: x for x in y["months"]}
    assert m["2026-11"]["complete"] is False  # starts mid-month
    assert m["2026-12"]["complete"] and m["2027-01"]["complete"] and not m["2027-02"]["complete"]
    assert m["2026-12"]["expenses_cents"] == 190_000 and m["2027-01"]["expenses_cents"] == 130_000
    assert y["biggest_decrease"] == {"from": "2026-12", "to": "2027-01", "change_cents": -60_000}
    assert y["biggest_increase"] is None
    assert y["highest_month"] == "2026-12" and y["average_month_expenses_cents"] == 160_000
    assert len(y["months"]) == 13 and not m["2027-11"]["started"]


def test_reimbursement_reduces_category_not_income(session):
    a = _setup(session)
    _t(session, a, "fee", date(2026, 12, 1), -500_000, "EDUCATION")
    _t(session, a, "back", date(2026, 12, 15), 400_000, "INCOME", "INCOME_CONTRACTOR", "EMPLOYER VENDOR PAY",
       category="Education")
    session.commit()
    y = year_summary(session, START, END, today=date(2026, 12, 31))
    assert y["by_category"] == {"Education": 100_000} and y["income_cents"] == 0


def test_deposits_to_review(session):
    a = _setup(session)
    _t(session, a, "pay", date(2026, 11, 6), 300_000, "INCOME", "INCOME_SALARY", "PAYROLL")
    _t(session, a, "odd", date(2026, 10, 1), 250_000, "INCOME", "INCOME_CONTRACTOR", "EMPLOYER VENDOR PAY")
    _t(session, a, "tiny", date(2026, 10, 2), 5_000, "INCOME", "INCOME_OTHER_INCOME", "CASHBACK")
    _t(session, a, "done", date(2026, 10, 3), 250_000, "INCOME", "INCOME_OTHER_INCOME", "BONUS", category="Income")
    _t(session, a, "zelle", date(2026, 10, 4), 90_000, "TRANSFER_IN", None, "Zelle from friend")
    session.commit()
    r = deposits_to_review(session, today=date(2026, 11, 10), regular_payers={"PAYROLL"})
    assert [x["description"] for x in r] == ["EMPLOYER VENDOR PAY"]

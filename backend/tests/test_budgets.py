"""Budgets. Made-up lines and amounts."""

import json
from datetime import date

from app.db.models import Account, AccountKind, DataSource, Transaction
from app.services.budgets import BudgetConfig, budget_progress


def _cfg(tmp_path, lines, start="2026-11-10"):
    p = tmp_path / "b.json"
    p.write_text(json.dumps({"year_start": start, "lines": lines}))
    return BudgetConfig.load(p)


def _acct(session):
    a = Account(name="Card", kind=AccountKind.CREDIT_CARD, source=DataSource.MANUAL, external_id="k", balance_cents=0)
    session.add(a)
    session.flush()
    return a


def _t(session, a, ext, d, cents, primary, detailed=None, category=None):
    session.add(Transaction(account_id=a.id, external_id=ext, posted_on=d, amount_cents=-cents, description=ext,
                            provider_category=primary, provider_category_detailed=detailed, category=category))


LINES = [
    {"name": "Eating out", "category": "Food & groceries", "exclude_sub": "groceries", "monthly": 300},
    {"name": "Groceries", "category": "Food & groceries", "sub": "groceries", "monthly": 200},
    {"name": "Fuel", "category": "Transport & travel", "sub": "fuel", "monthly": 100},
    {"name": "Travel", "category": "Travel", "exclude_sub": "fuel", "annual": 1200},  # old name accepted
]


def test_lines_pick_the_right_spending(session, tmp_path):
    a = _acct(session)
    _t(session, a, "before-year", date(2026, 11, 9), 99_999, "FOOD_AND_DRINK", "FOOD_AND_DRINK_RESTAURANT")
    _t(session, a, "dinner", date(2026, 11, 12), 4_000, "FOOD_AND_DRINK", "FOOD_AND_DRINK_RESTAURANT")
    _t(session, a, "market", date(2026, 11, 13), 3_000, "FOOD_AND_DRINK", "FOOD_AND_DRINK_GROCERIES")
    _t(session, a, "bigbox", date(2026, 11, 14), 2_000, "GENERAL_MERCHANDISE", "GENERAL_MERCHANDISE_SUPERSTORES")
    _t(session, a, "gas", date(2026, 11, 15), 5_000, "TRANSPORTATION", "TRANSPORTATION_GAS")
    _t(session, a, "taxi", date(2026, 11, 16), 1_500, "TRANSPORTATION", "TRANSPORTATION_TAXIS_AND_RIDE_SHARES")
    _t(session, a, "fixed", date(2026, 11, 17), 500, "FOOD_AND_DRINK", None, category="Groceries")  # your override
    session.commit()
    p = budget_progress(session, _cfg(tmp_path, LINES), today=date(2026, 11, 20))
    rows = {r["name"]: r for r in p["lines"]}
    assert rows["Eating out"]["month_spent_cents"] == 4_000  # the Nov 9 dinner is before the budget year
    assert rows["Groceries"]["month_spent_cents"] == 5_500  # market + superstore + your override
    assert rows["Fuel"]["month_spent_cents"] == 5_000
    assert rows["Travel"]["year_spent_cents"] == 1_500 and rows["Travel"]["annual_cents"] == 120_000


def test_first_month_cap_is_prorated_and_status(session, tmp_path):
    a = _acct(session)
    _t(session, a, "gas1", date(2026, 11, 11), 6_000, "TRANSPORTATION", "TRANSPORTATION_GAS")
    _t(session, a, "gas2", date(2026, 11, 18), 2_000, "TRANSPORTATION", "TRANSPORTATION_GAS")
    session.commit()
    p = budget_progress(session, _cfg(tmp_path, LINES), today=date(2026, 11, 20))
    fuel = {r["name"]: r for r in p["lines"]}["Fuel"]
    # Nov 10-30 is 21 of 30 days: cap 100 x 0.7 = 70; spent 80 -> over
    assert fuel["month_cap_cents"] == 7_000 and fuel["status"] == "over"
    assert p["month_share"] == 0.7
    # December: a full month, fresh cap; nothing spent yet
    p2 = budget_progress(session, _cfg(tmp_path, LINES), today=date(2026, 12, 5))
    fuel2 = {r["name"]: r for r in p2["lines"]}["Fuel"]
    assert fuel2["month_cap_cents"] == 10_000 and fuel2["month_spent_cents"] == 0
    assert fuel2["year_spent_cents"] == 8_000 and fuel2["status"] == "on track"


def test_annual_pace(session, tmp_path):
    a = _acct(session)
    lines = [{"name": "Trips", "category": "Transport & travel", "annual": 1200}]
    _t(session, a, "flight", date(2026, 11, 15), 30_000, "TRAVEL", "TRAVEL_FLIGHTS")
    session.commit()
    # 25% of the yearly limit spent early in the year: still fine (only 80%+ is flagged)
    assert budget_progress(session, _cfg(tmp_path, lines), today=date(2026, 11, 20))["lines"][0]["status"] == "on track"
    _t(session, a, "hotel", date(2026, 11, 16), 70_000, "TRAVEL", "TRAVEL_LODGING")
    session.commit()
    assert budget_progress(session, _cfg(tmp_path, lines), today=date(2026, 11, 20))["lines"][0]["status"] == "near"
    _t(session, a, "more", date(2026, 11, 17), 30_000, "TRAVEL", "TRAVEL_LODGING")
    session.commit()
    assert budget_progress(session, _cfg(tmp_path, lines), today=date(2026, 11, 20))["lines"][0]["status"] == "over"


def test_year_end_and_missing_file(tmp_path):
    assert BudgetConfig.load(tmp_path / "none.json") is None
    assert _cfg(tmp_path, [], start="2026-11-10").year_end == date(2027, 11, 9)

"""Recurring bill detection. Made-up merchants and amounts."""

from datetime import date

from app.db.models import Account, AccountKind, DataSource, ManualRecurring, SplitExpense, Transaction
from app.services.recurring import detect_recurring, monthly_total_cents

TODAY = date(2026, 11, 10)


def _acct(session):
    a = Account(name="Card", kind=AccountKind.CREDIT_CARD, source=DataSource.MANUAL, external_id="k", balance_cents=0)
    session.add(a)
    session.flush()
    return a


def _txns(session, acct, merchant, rows, primary="ENTERTAINMENT"):
    for i, (d, cents) in enumerate(rows):
        session.add(Transaction(account_id=acct.id, external_id=f"{merchant}{i}", posted_on=d,
                                amount_cents=-cents, description=merchant, provider_category=primary))


def _names(session, **kw):
    return {b.name: b for b in detect_recurring(session, today=TODAY, **kw)}


def test_steady_subscription_and_price_change(session):
    a = _acct(session)
    _txns(session, a, "StreamCo", [(date(2026, 8, 14), 999), (date(2026, 9, 14), 999), (date(2026, 10, 14), 1199)])
    _txns(session, a, "CloudBox", [(date(2026, 9, 30), 349), (date(2026, 10, 31), 349)])
    session.commit()
    bills = _names(session)
    assert bills["StreamCo"].amount_cents == 1199 and "was 9.99" in bills["StreamCo"].note
    assert bills["StreamCo"].next_expected == date(2026, 11, 14)
    assert bills["CloudBox"].amount_cents == 349
    assert monthly_total_cents(list(bills.values())) == 1548


def test_shopping_habits_are_not_subscriptions(session):
    a = _acct(session)
    # Similar-but-different amounts a month apart: a habit, not a subscription.
    _txns(session, a, "GrocerMart", [(date(2026, 9, 5), 5383), (date(2026, 10, 5), 5160)], "GENERAL_MERCHANDISE")
    # Exact repeat but only twice in a habit category: not enough.
    _txns(session, a, "Deli", [(date(2026, 9, 6), 809), (date(2026, 10, 6), 809)], "FOOD_AND_DRINK")
    # Exact repeat three months running in Food: a delivery membership.
    _txns(session, a, "FoodPass", [(date(2026, 9, 9), 999), (date(2026, 10, 9), 999), (date(2026, 11, 9), 999)],
          "FOOD_AND_DRINK")
    # Two price changes: not a stable subscription.
    _txns(session, a, "Wobbly", [(date(2026, 8, 1), 1000), (date(2026, 9, 1), 1200), (date(2026, 10, 1), 1400)])
    session.commit()
    assert set(_names(session)) == {"FoodPass"}


def test_lapsed_subscription_flagged(session):
    a = _acct(session)
    _txns(session, a, "OldGym", [(date(2026, 7, 1), 3000), (date(2026, 8, 1), 3000)], "PERSONAL_CARE")
    session.commit()
    b = _names(session)["OldGym"]
    assert b.active is False and b.next_expected is None
    assert monthly_total_cents([b]) == 0


def test_shared_bill_shows_your_share(session):
    a = _acct(session)
    _txns(session, a, "NetCo", [(date(2026, 9, 13), 6000), (date(2026, 10, 13), 6000)], "RENT_AND_UTILITIES")
    session.add(SplitExpense(external_id="x", spent_on=date(2026, 11, 1), group_name="g", description="Internet",
                             cost_cents=6000, you_paid_cents=6000, share_cents=3000, category="Bills & utilities"))
    session.commit()
    b = _names(session)["NetCo"]
    assert b.amount_cents == 3000 and "your share of 60.00" in b.note


def test_manual_bill_and_labels(session, tmp_path):
    a = _acct(session)
    _txns(session, a, "Fruit", [(date(2026, 9, 2), 349), (date(2026, 10, 2), 349)])
    _txns(session, a, "Fruit2", [(date(2026, 9, 3), 1199), (date(2026, 10, 3), 1199)])
    session.add(ManualRecurring(name="Phone plan share", amount_cents=2500, category="Bills & utilities",
                                day_of_month=20, paid_via="Splitwise"))
    session.commit()
    labels = tmp_path / "labels.json"
    labels.write_text('{"labels": [{"merchant": "Fruit", "max": 5, "label": "Storage"}]}')
    bills = _names(session, labels_path=labels)
    assert "Storage" in bills and "Fruit2" in bills
    phone = bills["Phone plan share"]
    assert phone.source == "manual" and phone.next_expected == date(2026, 11, 20)


def test_loans_and_saving_are_separate_from_bills(session):
    from app.db.models import LoanTerms

    a = _acct(session)
    # Steady monthly transfer into an investment account
    for i, d in enumerate([date(2026, 8, 20), date(2026, 9, 20), date(2026, 10, 20)]):
        session.add(Transaction(account_id=a.id, external_id=f"inv{i}", posted_on=d, amount_cents=-25_000,
                                description="BrokerCo", provider_category="TRANSFER_OUT",
                                provider_category_detailed="TRANSFER_OUT_INVESTMENT_AND_RETIREMENT_FUNDS"))
    # Ordinary transfers to friends are never recurring items
    for i, d in enumerate([date(2026, 9, 1), date(2026, 10, 1)]):
        session.add(Transaction(account_id=a.id, external_id=f"z{i}", posted_on=d, amount_cents=-4_000,
                                description="Zelle to Pat", provider_category="TRANSFER_OUT",
                                provider_category_detailed="TRANSFER_OUT_TRANSFER_OUT_FROM_APPS"))
    loan = Account(name="Car loan", kind=AccountKind.LOAN, source=DataSource.MANUAL, external_id="l",
                   balance_cents=500_000)
    session.add(loan)
    session.flush()
    session.add(LoanTerms(account_id=loan.id, principal_cents=500_000, balance_as_of=date(2026, 11, 1),
                          apr_bps=500, monthly_payment_cents=40_000, payment_day=15))
    session.commit()
    bills = detect_recurring(session, today=TODAY)
    kinds = {b.name: b.kind for b in bills}
    assert kinds == {"BrokerCo": "saving", "Car loan": "loan"}
    car = next(b for b in bills if b.kind == "loan")
    assert car.amount_cents == 40_000 and car.next_expected == date(2026, 11, 15)
    assert monthly_total_cents(bills) == 0  # no bills
    assert monthly_total_cents(bills, "saving") == 25_000 and monthly_total_cents(bills, None) == 65_000


def test_label_can_set_category(session, tmp_path):
    a = _acct(session)
    _txns(session, a, "WashPay", [(date(2026, 9, 1), 1000), (date(2026, 10, 1), 1000), (date(2026, 11, 1), 1000)],
          "FOOD_AND_DRINK")
    session.commit()
    labels = tmp_path / "l.json"
    labels.write_text('{"labels": [{"merchant": "WashPay", "label": "Laundry", "category": "Bills & utilities"}]}')
    b = _names(session, labels_path=labels)["Laundry"]
    assert b.category == "Bills & utilities"

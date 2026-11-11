"""Recurring bill detection. Made-up merchants and amounts."""

from datetime import date

from sqlalchemy import select

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
    _txns(session, a, "OldGym", [(date(2026, 7, 1), 3000), (date(2026, 8, 1), 3000)], "GENERAL_SERVICES")
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
    assert b.category == "Bills & subscriptions"


def test_planned_periodic_expense(session):
    session.add(ManualRecurring(name="Course fees", amount_cents=120_000, category="Education",
                                cadence="semester", next_due=date(2026, 12, 1), due_note="Dec or Jan"))
    session.commit()
    bills = detect_recurring(session, today=TODAY)
    b = bills[0]
    assert b.kind == "planned" and b.next_expected == date(2026, 12, 1)
    assert b.set_aside_cents == 20_000 and "due Dec or Jan" in b.note
    assert monthly_total_cents(bills) == 0 and monthly_total_cents(bills, None) == 0  # not a monthly outflow
    assert monthly_total_cents(bills, "planned") == 20_000


def test_paychecks_interest_and_bonus(session):
    chk = Account(name="Checking", kind=AccountKind.CHECKING, source=DataSource.MANUAL, external_id="c", balance_cents=0)
    sav = Account(name="Savings", kind=AccountKind.SAVINGS, source=DataSource.MANUAL, external_id="s", balance_cents=0)
    session.add_all([chk, sav])
    session.flush()
    pay = [(date(2026, 9, 11), 200_000), (date(2026, 9, 25), 200_000), (date(2026, 10, 9), 200_000),
           (date(2026, 10, 23), 210_000), (date(2026, 11, 6), 210_000)]  # a raise in October
    for i, (d, c) in enumerate(pay):
        session.add(Transaction(account_id=chk.id, external_id=f"p{i}", posted_on=d, amount_cents=c,
                                description="EMPLOYER PAYROLL", provider_category="INCOME",
                                provider_category_detailed="INCOME_SALARY"))
    for i, (d, c) in enumerate([(date(2026, 9, 5), 4_000), (date(2026, 10, 5), 4_500), (date(2026, 11, 5), 5_000)]):
        session.add(Transaction(account_id=sav.id, external_id=f"i{i}", posted_on=d, amount_cents=c,
                                description="Interest Payment", provider_category="INCOME",
                                provider_category_detailed="INCOME_INTEREST_EARNED"))
    # A one-off payment from the employer is not a pattern
    session.add(Transaction(account_id=chk.id, external_id="v", posted_on=date(2026, 9, 15), amount_cents=99_000,
                            description="EMPLOYER VENDOR PAY", provider_category="INCOME",
                            provider_category_detailed="INCOME_CONTRACTOR"))
    session.add(ManualRecurring(name="Bonus", amount_cents=0, category="Income", cadence="semiannual",
                                due_note="6,12"))
    session.commit()
    bills = {b.name: b for b in detect_recurring(session, today=TODAY) if b.kind == "income"}
    payroll = bills["EMPLOYER PAYROLL"]
    assert payroll.cadence == "biweekly" and payroll.amount_cents == 210_000
    assert payroll.next_expected == date(2026, 11, 20) and payroll.monthly_cents == 455_000  # 2,100 x 26 / 12
    assert "was 2,000.00" in payroll.note
    assert bills["Interest Payment"].cadence == "monthly" and bills["Interest Payment"].monthly_cents == 5_000
    assert "EMPLOYER VENDOR PAY" not in bills
    bonus = bills["Bonus"]
    assert bonus.next_expected == date(2026, 12, 1) and "every Jun & Dec" in bonus.note
    assert "amount not set yet" in bonus.note
    assert monthly_total_cents(list(bills.values()), "income") == 460_000
    assert monthly_total_cents(list(bills.values()), None) == 0  # income isn't an outflow


def test_paid_this_month(session):
    a = _acct(session)
    _txns(session, a, "PaidCo", [(date(2026, 10, 2), 500), (date(2026, 11, 2), 500)])
    _txns(session, a, "LaterCo", [(date(2026, 9, 20), 700), (date(2026, 10, 20), 700)])
    session.commit()
    bills = _names(session)
    assert bills["PaidCo"].paid_this_month is True and bills["LaterCo"].paid_this_month is False


def test_remove_hand_added_item(session):
    from app import cli

    session.add(ManualRecurring(name="Placeholder", amount_cents=0, category="Other"))
    session.commit()
    assert cli.main(["recurring-remove", "Nope"]) == 1
    assert cli.main(["recurring-remove", "Placeholder"]) == 0
    session.expire_all()
    assert session.scalars(select(ManualRecurring)).all() == []


def test_gym_membership_counts_after_two_months(session):
    a = _acct(session)
    for i, d in enumerate([date(2026, 9, 5), date(2026, 10, 5)]):
        session.add(Transaction(account_id=a.id, external_id=f"g{i}", posted_on=d, amount_cents=-2_500,
                                description="FitClub", provider_category="PERSONAL_CARE",
                                provider_category_detailed="PERSONAL_CARE_GYMS_AND_FITNESS_CENTERS"))
    session.commit()
    assert "FitClub" in _names(session)


def test_hand_added_bill_steps_aside_when_detected(session, tmp_path):
    a = _acct(session)
    session.add(ManualRecurring(name="Gym", amount_cents=2_800, category="Personal care & shopping", day_of_month=30))
    session.commit()
    assert [b.source for b in detect_recurring(session, today=TODAY)] == ["manual"]
    labels = tmp_path / "l.json"
    labels.write_text('{"labels": [{"merchant": "FitPlace", "label": "Gym"}]}')
    for i, d in enumerate([date(2026, 9, 30), date(2026, 10, 30)]):
        session.add(Transaction(account_id=a.id, external_id=f"g{i}", posted_on=d, amount_cents=-2_800,
                                description="FitPlace", provider_category="PERSONAL_CARE",
                                provider_category_detailed="PERSONAL_CARE_GYMS_AND_FITNESS_CENTERS"))
    session.commit()
    bills = detect_recurring(session, today=TODAY, labels_path=labels)
    assert [(b.name, b.source) for b in bills] == [("Gym", "detected")]

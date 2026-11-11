"""Hand-entered loans. Numbers are made up and checked by hand in the comments."""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import cli
from app.api.plaid import get_plaid_client
from app.db.models import Account, AccountKind, DataSource, LoanTerms
from app.main import app
from app.services.loans import (
    estimate_balance,
    monthly_interest_cents,
    months_to_payoff,
    payment_dates,
    refresh_manual_loans,
)
from app.services.networth import compute_net_worth
from tests.fake_plaid import FakePlaid


def _terms(principal=1_000_000, apr_bps=600, payment=50_000, day=15, as_of=date(2026, 10, 1)):
    return LoanTerms(
        principal_cents=principal,
        apr_bps=apr_bps,
        monthly_payment_cents=payment,
        payment_day=day,
        balance_as_of=as_of,
    )


def test_two_payments_by_hand():
    # $10,000 at 6% APR (0.5%/month), $500 payment on the 15th:
    #   Oct 15: interest $50.00,  10,000.00 + 50.00 − 500 = 9,550.00
    #   Nov 15: interest $47.75,   9,550.00 + 47.75 − 500 = 9,097.75
    est = estimate_balance(_terms(), date(2026, 11, 20))
    assert (est.balance_cents, est.payments_applied, est.interest_paid_cents) == (909_775, 2, 9_775)


def test_no_payment_yet_means_statement_balance():
    assert estimate_balance(_terms(), date(2026, 10, 14)).balance_cents == 1_000_000


def test_payment_on_statement_date_is_already_in_the_balance():
    t = _terms(as_of=date(2026, 10, 15))
    assert payment_dates(t.balance_as_of, date(2026, 11, 15), 15) == [date(2026, 11, 15)]


def test_year_rollover():
    assert payment_dates(date(2026, 12, 20), date(2027, 2, 5), 5) == [date(2027, 1, 5), date(2027, 2, 5)]


def test_balance_never_negative_and_payoff_count():
    assert estimate_balance(_terms(principal=20_000, apr_bps=0), date(2027, 1, 1)).balance_cents == 0
    # $1,000 at 0%, $300/month: 300, 300, 300, 100 -> 4 payments
    assert months_to_payoff(_terms(principal=100_000, apr_bps=0, payment=30_000), 100_000) == 4
    # 12% APR on $10,000 = $100/month interest; a $100 payment never pays it down
    assert months_to_payoff(_terms(apr_bps=1200, payment=10_000), 1_000_000) is None


def test_interest_rounding():
    assert monthly_interest_cents(955_000, 600) == 4_775
    assert monthly_interest_cents(1, 600) == 0


def test_loan_set_command_creates_a_liability(session, capsys):
    today = date.today().isoformat()
    args = ["loan-set", "--name", "Car loan", "--institution", "Example Auto Finance",
            "--balance", "15,000.00", "--as-of", today, "--apr", "5.49",
            "--payment", "450.00", "--day", "15"]
    assert cli.main(args) == 0
    acct = session.scalar(select(Account).where(Account.name == "Car loan"))
    assert acct.kind == AccountKind.LOAN and acct.source == DataSource.MANUAL
    assert acct.balance_cents == 1_500_000
    terms = session.scalar(select(LoanTerms))
    assert (terms.apr_bps, terms.monthly_payment_cents, terms.payment_day) == (549, 45_000, 15)
    assert compute_net_worth(session).liabilities_cents == 1_500_000
    assert "Saved loan 'Car loan'" in capsys.readouterr().out

    # Running it again with a newer statement updates instead of duplicating.
    args[args.index("15,000.00")] = "14,600.00"
    cli.main(args)
    session.expire_all()
    assert len(session.scalars(select(Account)).all()) == 1
    assert session.scalar(select(Account)).balance_cents == 1_460_000


def test_bad_payment_day_rejected(session):
    args = ["loan-set", "--name", "x", "--institution", "y", "--balance", "1", "--as-of",
            "2026-01-01", "--apr", "1", "--payment", "1", "--day", "31"]
    assert cli.main(args) == 1


def _add_loan(session, as_of):
    acct = Account(name="Car loan", kind=AccountKind.LOAN, source=DataSource.MANUAL,
                   external_id="loan-car", balance_cents=1_000_000)
    session.add(acct)
    session.flush()
    t = _terms(as_of=as_of)
    t.account_id = acct.id
    session.add(t)
    session.commit()
    return acct


def test_refresh_moves_balance_and_records_history(session):
    acct = _add_loan(session, date(2026, 10, 1))
    assert refresh_manual_loans(session, today=date(2026, 11, 20)) == 1
    assert acct.balance_cents == 909_775
    assert refresh_manual_loans(session, today=date(2026, 11, 20)) == 0  # no change, no new snapshot


def test_sync_now_also_refreshes_loans(session):
    acct = _add_loan(session, date(2026, 1, 1))  # many payments ago
    app.dependency_overrides[get_plaid_client] = FakePlaid().client
    with TestClient(app, base_url="http://localhost") as c:
        c.post("/plaid/sync")
    app.dependency_overrides.clear()
    session.refresh(acct)
    assert acct.balance_cents < 1_000_000


# ---- payment tracking (made-up numbers) ----
#   Statement: $8,000.00 owed on 2026-08-31, 6.00% APR, daily interest.
#   Bank posts payments 1 day after the lender credits them.
#   Paid $600, bank 09-29 -> credited 09-28: 28 days interest = $36.82 -> 7,436.82
#   Paid $800, bank 11-03 -> credited 11-02: 35 days interest = $42.79 -> 6,679.61


def _tracked_loan(session, as_of=date(2026, 8, 31), principal=800_000):
    bank = Account(name="Checking", kind=AccountKind.CHECKING, source=DataSource.MANUAL,
                   external_id="chk", balance_cents=0)
    loan = Account(name="Car loan", kind=AccountKind.LOAN, source=DataSource.MANUAL,
                   external_id="loan-car", balance_cents=principal)
    session.add_all([bank, loan])
    session.flush()
    t = _terms(principal=principal, as_of=as_of)
    t.account_id, t.payment_match, t.posting_lag_days = loan.id, "example auto", 1
    session.add(t)
    session.commit()
    return bank, loan, t


def _txn(session, bank, ext, posted, cents, desc="EXAMPLE AUTO FINANCE PMT"):
    from app.db.models import Transaction

    session.add(Transaction(account_id=bank.id, external_id=ext, posted_on=posted,
                            amount_cents=cents, description=desc))
    session.commit()


def test_tracked_payments_use_daily_interest(session):
    bank, loan, t = _tracked_loan(session)
    _txn(session, bank, "p1", date(2026, 9, 29), -60_000)
    _txn(session, bank, "p2", date(2026, 11, 3), -80_000)
    est = estimate_balance(t, date(2026, 11, 10), session)
    assert [p.effective_on for p in est.payments] == [date(2026, 9, 28), date(2026, 11, 2)]
    assert est.interest_paid_cents == 3_682 + 4_279
    assert est.balance_cents == 667_961


def test_tracking_ignores_unrelated_refunds_and_already_counted(session):
    bank, loan, t = _tracked_loan(session, as_of=date(2026, 11, 2), principal=667_961)
    _txn(session, bank, "in-stmt", date(2026, 11, 3), -80_000)  # credited 11-02: already in statement
    _txn(session, bank, "refund", date(2026, 11, 5), 5_000)  # money in: not a payment
    _txn(session, bank, "other", date(2026, 11, 6), -9_999, desc="GROCERY STORE")
    _txn(session, bank, "future", date(2026, 12, 1), -50_000)  # after "today"
    est = estimate_balance(t, date(2026, 11, 10), session)
    assert est.payments == [] and est.balance_cents == 667_961


def test_tracked_payment_flows_into_net_worth_on_refresh(session):
    bank, loan, t = _tracked_loan(session)
    _txn(session, bank, "p1", date(2026, 9, 29), -60_000)
    refresh_manual_loans(session, today=date(2026, 10, 1))
    session.refresh(loan)
    assert loan.balance_cents == 743_682
    assert compute_net_worth(session).liabilities_cents == 743_682


def test_loan_set_tracking_flags(session):
    args = ["loan-set", "--name", "Car loan", "--institution", "Example Auto Finance",
            "--balance", "100.00", "--as-of", "2026-01-01", "--apr", "6", "--payment", "50",
            "--day", "9", "--payment-match", "Example Auto", "--posting-lag", "1"]
    assert cli.main(args) == 0
    t = session.scalar(select(LoanTerms))
    assert (t.payment_match, t.posting_lag_days) == ("Example Auto", 1)


def test_unpaid_interest_is_paid_before_principal(session):
    # Statement: $6,679.61 owed on 11-02 plus $10.00 interest left unpaid.
    # Paid $600, credited 11-10: 8 days interest $8.78 + $10.00 = $18.78
    #   principal 600 − 18.78 = 581.22 -> 6,098.39
    bank, loan, t = _tracked_loan(session, as_of=date(2026, 11, 2), principal=667_961)
    t.unpaid_interest_cents = 1_000
    session.commit()
    _txn(session, bank, "p3", date(2026, 11, 11), -60_000)
    est = estimate_balance(t, date(2026, 11, 12), session)
    assert est.interest_paid_cents == 1_878 and est.balance_cents == 609_839


def test_payment_smaller_than_interest_leaves_principal_untouched(session):
    bank, loan, t = _tracked_loan(session, as_of=date(2026, 11, 2), principal=667_961)
    t.unpaid_interest_cents = 1_000
    session.commit()
    _txn(session, bank, "tiny", date(2026, 11, 11), -500)  # $5 < $18.78 owed
    est = estimate_balance(t, date(2026, 11, 12), session)
    assert est.balance_cents == 667_961 and est.interest_paid_cents == 500

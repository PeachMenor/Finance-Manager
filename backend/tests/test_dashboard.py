from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Account, AccountKind, BalanceSnapshot, DataSource
from app.integrations.demo import DEMO_PEOPLE, EXPECTED_NET_WORTH_CENTS, DemoBankIntegration
from app.main import app
from app.services.dashboard import build_dashboard, net_worth_history
from app.services.sync import sync_accounts, sync_person_balances


def _demo(session):
    bank = DemoBankIntegration()
    sync_accounts(session, bank.source, bank.fetch_accounts())
    sync_person_balances(session, DataSource.SPLITWISE, DEMO_PEOPLE)


def test_groups_and_totals_match_net_worth(session):
    _demo(session)
    d = build_dashboard(session)
    g = {x["key"]: x for x in d["groups"]}
    assert g["cash"]["total_cents"] == 1_250_000  # 2,500 checking + 10,000 savings
    assert g["investments"]["total_cents"] == 2_620_000  # 5,000 + 20,000 401k + 1,200 HSA
    assert g["cards"]["total_cents"] == 75_025
    assert g["loans"]["total_cents"] == 1_500_000
    assets = g["cash"]["total_cents"] + g["investments"]["total_cents"]
    debts = g["cards"]["total_cents"] + g["loans"]["total_cents"]
    assert assets - debts + 4_000 - 2_550 == d["net_worth_cents"] == EXPECTED_NET_WORTH_CENTS
    assert d["people"] == [{"name": "Alex", "amount_cents": 4000}, {"name": "Sam", "amount_cents": -2550}]


def test_not_counted_and_hidden(session):
    _demo(session)
    k401 = session.scalar(select(Account).where(Account.external_id == "demo-401k"))
    k401.include_in_net_worth = False
    hsa = session.scalar(select(Account).where(Account.external_id == "demo-hsa"))
    hsa.hidden = True
    session.commit()
    d = build_dashboard(session)
    g = {x["key"]: x for x in d["groups"]}
    # 401k moves out of investments into "shown, not counted"
    assert [a["name"] for a in d["not_counted"]["accounts"]] == ["Demo 401k"]
    assert d["not_counted"]["total_cents"] == 2_000_000
    assert d["net_worth_cents"] == EXPECTED_NET_WORTH_CENTS - 2_000_000
    # hidden HSA: not listed, but still in the investments total
    assert "Demo HSA" not in [a["name"] for a in g["investments"]["accounts"]]
    assert g["investments"]["total_cents"] == 500_000 + 120_000


def _snap(session, acct, day, cents):
    session.add(BalanceSnapshot(account_id=acct.id, balance_cents=cents,
                                taken_at=datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)))


def test_history_carries_last_balance_forward(session):
    today = date.today()
    d0, d1 = today - timedelta(days=3), today - timedelta(days=1)
    # Current balances equal each account's latest snapshot, as after a real sync.
    cash = Account(name="Cash", kind=AccountKind.SAVINGS, source=DataSource.MANUAL, external_id="c", balance_cents=150_000)
    card = Account(name="Card", kind=AccountKind.CREDIT_CARD, source=DataSource.MANUAL, external_id="k", balance_cents=10_000)
    gone = Account(name="401k", kind=AccountKind.RETIREMENT, source=DataSource.MANUAL, external_id="r",
                   balance_cents=0, include_in_net_worth=False)
    session.add_all([cash, card, gone])
    session.flush()
    _snap(session, cash, d0, 100_000)
    _snap(session, card, d0, 10_000)
    _snap(session, gone, d0, 999_999)  # not counted: never in the line
    _snap(session, cash, d1, 150_000)  # card unchanged since d0 -> carried forward
    session.commit()
    h = net_worth_history(session)
    assert [x["date"] for x in h][0] == d0.isoformat() and h[-1]["date"] == today.isoformat()
    by_day = {x["date"]: x["net_worth_cents"] for x in h}
    assert by_day[d0.isoformat()] == 90_000
    assert by_day[(d0 + timedelta(days=1)).isoformat()] == 90_000  # no new data: carried
    assert by_day[d1.isoformat()] == 140_000
    assert by_day[today.isoformat()] == 140_000


def test_dashboard_routes(session):
    _demo(session)
    with TestClient(app, base_url="http://localhost") as c:
        page = c.get("/")
        data = c.get("/dashboard").json()
    assert page.status_code == 200 and "Ledger" in page.text
    assert "<script src=" not in page.text  # no external scripts on the dashboard
    assert data["net_worth_cents"] == EXPECTED_NET_WORTH_CENTS
    assert len(data["history"]) >= 1


def test_history_uses_local_dates(session, monkeypatch):
    # 03:00 UTC on Nov 11 is the evening of Nov 10 in California.
    import time

    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    try:
        cash = Account(name="Cash", kind=AccountKind.SAVINGS, source=DataSource.MANUAL,
                       external_id="c", balance_cents=0)
        session.add(cash)
        session.flush()
        session.add(BalanceSnapshot(account_id=cash.id, balance_cents=5_000,
                                    taken_at=datetime(2026, 11, 11, 3, 0, tzinfo=timezone.utc)))
        session.commit()
        assert net_worth_history(session)[0]["date"] == "2026-11-10"
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()


def test_todays_point_matches_headline_even_without_history(session):
    _demo(session)
    # An account with no balance history at all (e.g. entered by hand) still counts today.
    session.add(Account(name="Loan", kind=AccountKind.LOAN, source=DataSource.MANUAL,
                        external_id="no-history", balance_cents=100_000))
    session.commit()
    d = build_dashboard(session)
    assert d["history"][-1]["net_worth_cents"] == d["net_worth_cents"] == EXPECTED_NET_WORTH_CENTS - 100_000


def test_loan_set_records_history(session):
    from app import cli

    cli.main(["loan-set", "--name", "Car loan", "--institution", "Example Auto Finance", "--balance", "500",
              "--as-of", date.today().isoformat(), "--apr", "6", "--payment", "50", "--day", "9"])
    assert session.scalar(select(BalanceSnapshot.balance_cents)) == 50_000


def test_dashboard_includes_spending_months(session):
    _demo(session)
    d = build_dashboard(session)
    assert d["spending"]["categories"][0] == "Rent"
    assert len(d["spending"]["months"]) == 6


def test_dashboard_reports_shared_coverage(session):
    from app.db.models import SplitExpense

    _demo(session)
    assert build_dashboard(session)["spending"]["shared_from"] is None
    session.add(SplitExpense(external_id="x", spent_on=date(2026, 11, 1), group_name="g", description="Rent",
                             cost_cents=100, you_paid_cents=100, share_cents=50, category="Rent"))
    session.commit()
    assert build_dashboard(session)["spending"]["shared_from"] == "2026-11-01"


def test_dashboard_includes_recurring(session):
    d = build_dashboard(session)
    assert d["recurring"]["bills"] == [] and d["recurring"]["all_monthly_cents"] == 0
    assert d["recurring"]["totals"] == {"income": 0, "bill": 0, "loan": 0, "saving": 0, "planned": 0}


def test_dashboard_budgets_absent_without_file(session):
    assert build_dashboard(session)["budgets"] is None

"""Monthly report numbers and PDF. Made-up data."""

from datetime import date, datetime, timezone

from app.db.models import Account, AccountKind, BalanceSnapshot, DataSource, Transaction
from app.services.report import build_month_report, prev_month, season_months
from app.services.report_pdf import render_month_report


def test_month_and_season_helpers():
    assert prev_month("2027-01") == "2026-12" and prev_month("2026-11") == "2026-10"
    assert season_months("2026-11") == ["2026-09", "2026-10", "2026-11"]
    assert season_months("2027-01") == ["2026-12", "2027-01", "2027-02"]
    assert season_months("2026-12") == ["2026-12", "2027-01", "2027-02"]


def _snap(session, acct, d, cents):
    session.add(BalanceSnapshot(account_id=acct.id, balance_cents=cents,
                                taken_at=datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc)))


def test_report_compares_with_previous_month(session, tmp_path):
    chk = Account(name="Checking", kind=AccountKind.CHECKING, source=DataSource.MANUAL, external_id="c", balance_cents=0)
    brk = Account(name="Broker", kind=AccountKind.BROKERAGE, source=DataSource.MANUAL, external_id="b", balance_cents=0)
    session.add_all([chk, brk])
    session.flush()
    for ext, d, cents, primary, det in [
        ("p1", date(2026, 11, 6), 300_000, "INCOME", "INCOME_SALARY"),
        ("f1", date(2026, 11, 8), -50_000, "FOOD_AND_DRINK", None),
        ("p2", date(2026, 12, 4), 300_000, "INCOME", "INCOME_SALARY"),
        ("f2", date(2026, 12, 8), -80_000, "FOOD_AND_DRINK", None),
        ("t2", date(2026, 12, 9), -20_000, "TRAVEL", None),
    ]:
        session.add(Transaction(account_id=chk.id, external_id=ext, posted_on=d, amount_cents=cents,
                                description=ext, provider_category=primary, provider_category_detailed=det))
    _snap(session, chk, date(2026, 11, 30), 100_000)
    _snap(session, brk, date(2026, 11, 30), 500_000)
    _snap(session, chk, date(2026, 12, 31), 150_000)
    _snap(session, brk, date(2026, 12, 20), 550_000)
    session.commit()
    r = build_month_report(session, "2026-12", today=date(2027, 1, 1), tracking_start=date(2026, 11, 1),
                           holdings=[{"name": "Broker", "account_ids": [brk.id]}])
    assert r["complete"] is True
    assert (r["this"]["income_cents"], r["this"]["expenses_cents"]) == (300_000, 100_000)
    assert r["previous"]["expenses_cents"] == 50_000
    assert r["net_worth_end_cents"] == 700_000 and r["net_worth_prev_end_cents"] == 600_000
    assert r["holdings"] == [{"name": "Broker", "end_cents": 550_000, "prev_end_cents": 500_000}]
    assert r["season"]["name"] == "Winter 2026-27" and r["season"]["previous_name"] == "Fall 2026"
    assert r["season"]["previous"]["months"] == ["2026-11"]  # tracking started in November
    out = render_month_report(r, tmp_path / "r.pdf")
    assert out.read_bytes()[:4] == b"%PDF"


def test_first_month_has_no_previous(session, tmp_path):
    r = build_month_report(session, "2026-11", today=date(2026, 11, 15), tracking_start=date(2026, 11, 1))
    assert r["previous"] is None and r["net_worth_prev_end_cents"] is None and r["complete"] is False
    assert render_month_report(r, tmp_path / "x.pdf").exists()

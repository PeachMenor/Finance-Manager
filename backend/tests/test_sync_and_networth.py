from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import (
    Account,
    AccountKind,
    BalanceSnapshot,
    DataSource,
    Holding,
    Transaction,
)
from app.integrations.base import FetchedAccount, FetchedHolding, FetchedTransaction
from app.integrations.demo import DEMO_PEOPLE, EXPECTED_NET_WORTH_CENTS, DemoBankIntegration
from app.main import app
from app.services.networth import compute_net_worth
from app.services.sync import sync_accounts, sync_person_balances

SRC = DataSource.MANUAL


def _load_demo(session):
    bank = DemoBankIntegration()
    sync_accounts(session, bank.source, bank.fetch_accounts())
    sync_person_balances(session, DataSource.SPLITWISE, DEMO_PEOPLE)


def test_demo_net_worth_matches_hand_calculation(session):
    _load_demo(session)
    s = compute_net_worth(session)
    assert s.assets_cents == 3_870_000
    assert s.liabilities_cents == 1_575_025
    assert s.owed_to_you_cents == 4_000
    assert s.you_owe_cents == 2_550
    assert s.net_worth_cents == EXPECTED_NET_WORTH_CENTS == 2_296_425
    assert [name for name, _ in s.people] == ["Alex", "Sam"]  # settled Kim dropped


def test_resync_updates_without_duplicates(session):
    bank = DemoBankIntegration()
    sync_accounts(session, SRC, bank.fetch_accounts())
    again = sync_accounts(session, SRC, bank.fetch_accounts())
    assert again.new_transactions == 0 and again.updated_transactions == 4
    assert len(session.scalars(select(Account)).all()) == 7
    assert len(session.scalars(select(Transaction)).all()) == 4
    assert len(session.scalars(select(BalanceSnapshot)).all()) == 14  # history kept


def _one(balance, txns=(), removed=(), holdings=None):
    return [
        FetchedAccount(
            external_id="a1",
            institution_name="Bank",
            name="Checking",
            kind=AccountKind.CHECKING,
            balance_cents=balance,
            transactions=list(txns),
            removed_transaction_ids=list(removed),
            holdings=holdings,
        )
    ]


def test_balance_change_removed_txn_and_kept_category(session):
    t = FetchedTransaction("t1", date(2026, 11, 1), -500, "Lunch")
    sync_accounts(session, SRC, _one(1000, [t, FetchedTransaction("t2", date(2026, 11, 1), -1, "x")]))
    row = session.scalar(select(Transaction).where(Transaction.external_id == "t1"))
    row.category = "Food"  # user categorized it
    session.commit()

    t_fixed = FetchedTransaction("t1", date(2026, 11, 1), -550, "Lunch + tip")
    result = sync_accounts(session, SRC, _one(900, [t_fixed], removed=["t2"]))
    assert result.removed_transactions == 1
    row = session.scalar(select(Transaction).where(Transaction.external_id == "t1"))
    assert (row.amount_cents, row.description, row.category) == (-550, "Lunch + tip", "Food")
    assert session.scalar(select(Account)).balance_cents == 900


def test_holdings_replaced_only_when_provided(session):
    sync_accounts(session, SRC, _one(0, holdings=[FetchedHolding("VOO", 1.0)]))
    sync_accounts(session, SRC, _one(0, holdings=None))  # provider silent -> keep
    assert [h.symbol for h in session.scalars(select(Holding))] == ["VOO"]
    sync_accounts(session, SRC, _one(0, holdings=[FetchedHolding("VTI", 2.0)]))
    assert [h.symbol for h in session.scalars(select(Holding))] == ["VTI"]


def test_excluded_accounts_not_counted(session):
    _load_demo(session)
    session.add(
        Account(
            name="Unvested RSUs",
            kind=AccountKind.OTHER,
            source=DataSource.MANUAL,
            external_id="rsu",
            balance_cents=50_000_00,
            include_in_net_worth=False,
        )
    )
    session.commit()
    s = compute_net_worth(session)
    assert s.excluded_cents == 5_000_000
    assert s.net_worth_cents == EXPECTED_NET_WORTH_CENTS  # unchanged


def test_summary_endpoint(session):
    _load_demo(session)
    with TestClient(app) as client:
        body = client.get("/summary").json()
    assert body["net_worth_cents"] == EXPECTED_NET_WORTH_CENTS
    assert body["people"] == [
        {"name": "Alex", "amount_cents": 4000},
        {"name": "Sam", "amount_cents": -2550},
    ]

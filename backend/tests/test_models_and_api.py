from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Account,
    AccountKind,
    DataSource,
    Holding,
    Institution,
    Transaction,
)
from app.main import app


def _make_account(session, external_id="acc-1", kind=AccountKind.CHECKING):
    bank = Institution(name="Test Bank")
    acct = Account(
        institution=bank,
        name="Everyday Checking",
        kind=kind,
        source=DataSource.MANUAL,
        external_id=external_id,
        balance_cents=150_00,
    )
    session.add(acct)
    session.commit()
    return acct


def test_account_with_transactions_and_holdings(session):
    acct = _make_account(session, kind=AccountKind.BROKERAGE)
    session.add_all(
        [
            Transaction(
                account=acct,
                external_id="t1",
                posted_on=date(2026, 11, 1),
                amount_cents=-12_50,
                description="Coffee",
            ),
            Holding(account=acct, symbol="VOO", quantity=1.5),
        ]
    )
    session.commit()
    session.refresh(acct)
    assert acct.transactions[0].amount_cents == -1250
    assert acct.holdings[0].symbol == "VOO"


def test_resync_cannot_duplicate_an_account(session):
    _make_account(session)
    with pytest.raises(IntegrityError):
        session.add(
            Account(
                name="dup",
                kind=AccountKind.CHECKING,
                source=DataSource.MANUAL,
                external_id="acc-1",
            )
        )
        session.commit()


def test_liability_kinds():
    assert AccountKind.CREDIT_CARD.is_liability
    assert AccountKind.LOAN.is_liability
    assert not AccountKind.SAVINGS.is_liability


def test_health_and_accounts_endpoints(session):
    _make_account(session)
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        accounts = client.get("/accounts").json()
    assert accounts == [
        {
            "id": 1,
            "name": "Everyday Checking",
            "institution": "Test Bank",
            "kind": "checking",
            "balance_cents": 15000,
            "currency": "USD",
        }
    ]

from datetime import date

import pytest
from sqlalchemy import select

from app.db.models import AccountKind, PlaidItem, Transaction
from app.integrations.plaid import PlaidError, PlaidIntegration, map_account_kind
from app.services.networth import compute_net_worth
from app.services.sync import sync_plaid_items
from tests.fake_plaid import FakePlaid


def _fetch(fake: FakePlaid, cursor=None):
    integ = PlaidIntegration(fake.client(), "tok-1", cursor=cursor)
    return integ, {a.external_id: a for a in integ.fetch_accounts()}


def test_balances_and_kinds():
    _, accts = _fetch(FakePlaid())
    assert {k: (a.kind, a.balance_cents) for k, a in accts.items()} == {
        "chk": (AccountKind.CHECKING, 110000),
        "sav": (AccountKind.SAVINGS, 250050),  # current missing -> falls back to available
        "cc": (AccountKind.CREDIT_CARD, 41025),
        "401k": (AccountKind.RETIREMENT, 2363198),
        "auto": (AccountKind.LOAN, 1200000),
    }
    assert all(a.institution_name == "Test Platypus Bank" for a in accts.values())


def test_transactions_signs_pending_pagination_and_removed():
    integ, accts = _fetch(FakePlaid())
    chk = {t.external_id: t for t in accts["chk"].transactions}
    assert chk["t-coffee"].amount_cents == -433  # money out -> negative
    assert chk["t-coffee"].description == "Starbucks"  # merchant name preferred
    assert chk["t-pay"].amount_cents == 250000  # money in -> positive (from page 2)
    assert "t-pending" not in chk  # pending skipped
    assert accts["cc"].transactions[0].description == "Dinner"
    assert accts["chk"].removed_transaction_ids == ["t-old"]
    assert integ.next_cursor == "c2"


def test_next_sync_sends_saved_cursor():
    fake = FakePlaid()
    _fetch(fake, cursor="c2")
    sync_calls = [body for path, body in fake.requests if path == "/transactions/sync"]
    assert sync_calls[0]["cursor"] == "c2"


def test_holdings_only_on_investment_accounts():
    _, accts = _fetch(FakePlaid())
    h = {x.symbol: x for x in accts["401k"].holdings}
    assert h["VOO"].quantity == 50.0 and h["VOO"].cost_basis_cents == 2_000_000
    assert h["Cash"].cost_basis_cents is None  # no ticker -> security name
    assert accts["chk"].holdings is None  # not an investment account


def test_login_without_investments_product_still_syncs():
    _, accts = _fetch(FakePlaid(fail={"/investments/holdings/get": "PRODUCTS_NOT_SUPPORTED"}))
    assert accts["401k"].holdings == []
    assert accts["chk"].balance_cents == 110000


def test_real_errors_raise_without_leaking_secrets():
    with pytest.raises(PlaidError) as err:
        _fetch(FakePlaid(fail={"/accounts/balance/get": "INVALID_ACCESS_TOKEN"}))
    assert err.value.error_code == "INVALID_ACCESS_TOKEN"
    assert "sec" not in str(err.value) and "tok-1" not in str(err.value)


def test_every_request_carries_credentials():
    fake = FakePlaid()
    _fetch(fake)
    assert all(b["client_id"] == "cid" and b["secret"] == "sec" for _, b in fake.requests)


@pytest.mark.parametrize(
    "ptype, subtype, kind",
    [
        ("depository", "hsa", AccountKind.HSA),
        ("investment", "hsa", AccountKind.HSA),
        ("investment", "roth", AccountKind.RETIREMENT),
        ("investment", "brokerage", AccountKind.BROKERAGE),
        ("investment", "stock plan", AccountKind.BROKERAGE),
        ("investment", "crypto exchange", AccountKind.CRYPTO),
        ("depository", "cd", AccountKind.SAVINGS),
        ("other", None, AccountKind.OTHER),
    ],
)
def test_map_account_kind(ptype, subtype, kind):
    assert map_account_kind(ptype, subtype) == kind


def test_full_plaid_sync_into_database(session):
    fake = FakePlaid()
    session.add(PlaidItem(item_id="item-1", access_token="tok-1"))
    session.commit()

    first = sync_plaid_items(session, fake.client())
    assert first.accounts == 5 and first.new_transactions == 3

    item = session.scalar(select(PlaidItem))
    assert item.cursor == "c2" and item.institution_name == "Test Platypus Bank"

    # Second run starts from the saved cursor: nothing new, nothing duplicated.
    second = sync_plaid_items(session, fake.client())
    assert second.new_transactions == 0
    assert len(session.scalars(select(Transaction)).all()) == 3

    # 1,100.00 + 2,500.50 + 23,631.98 − 410.25 − 12,000.00 = 14,822.23
    assert compute_net_worth(session).net_worth_cents == 1_482_223
    assert date(2026, 11, 1) in {t.posted_on for t in session.scalars(select(Transaction))}

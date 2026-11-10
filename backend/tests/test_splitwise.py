import httpx
import pytest

from app.db.models import DataSource
from app.integrations.splitwise import SplitwiseClient, SplitwiseError
from app.services.networth import compute_net_worth
from app.services.sync import sync_person_balances

FRIENDS = {
    "friends": [
        {"id": 1, "first_name": "Alex", "last_name": "Lee",
         "balance": [{"currency_code": "USD", "amount": "40.0"}]},
        {"id": 2, "first_name": "Sam", "last_name": None,
         "balance": [{"currency_code": "USD", "amount": "-25.5"},
                     {"currency_code": "EUR", "amount": "10.0"}]},
        {"id": 3, "first_name": "Kim", "last_name": "Park", "balance": []},  # settled
    ]
}


def _client(status=200, payload=FRIENDS, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=payload)

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://sw.test")
    return SplitwiseClient("k", http=http)


def test_fetch_balances_parses_people_and_currencies():
    seen = []
    balances = _client(seen=seen).fetch_balances()
    assert [(b.name, b.amount_cents, b.currency) for b in balances] == [
        ("Alex Lee", 4000, "USD"),
        ("Sam", -2550, "USD"),
        ("Sam", 1000, "EUR"),
    ]
    assert seen[0].url.path == "/get_friends"
    assert seen[0].headers["Authorization"] == "Bearer k"


def test_http_error_raises():
    with pytest.raises(SplitwiseError):
        _client(status=401, payload={"errors": {}}).fetch_balances()


def test_owed_and_owing_totals(session):
    sync_person_balances(session, DataSource.SPLITWISE, _client().fetch_balances())
    s = compute_net_worth(session)
    assert s.owed_to_you_cents == 4000
    assert s.you_owe_cents == 2550
    assert s.net_worth_cents == 1450  # only USD counted; EUR ignored
    # A re-sync after settling up replaces old balances.
    sync_person_balances(session, DataSource.SPLITWISE, [])
    assert compute_net_worth(session).people == []

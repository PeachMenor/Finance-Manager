"""The link-page routes, run against the fake Plaid server (no real keys)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.plaid import get_plaid_client
from app.db.models import PlaidItem
from app.main import app
from tests.fake_plaid import FakePlaid


@pytest.fixture()
def fake():
    return FakePlaid()


@pytest.fixture()
def client(session, fake):
    app.dependency_overrides[get_plaid_client] = fake.client
    with TestClient(app, base_url="http://localhost") as c:
        yield c
    app.dependency_overrides.clear()


def test_link_page_served(client):
    r = client.get("/link")
    assert r.status_code == 200
    assert "cdn.plaid.com/link/v2/stable/link-initialize.js" in r.text


@pytest.mark.parametrize(
    "kind, products, optional",
    [("banking", ["transactions"], ["investments"]),
     ("investments", ["investments"], ["transactions"])],
)
def test_link_token_products(client, fake, kind, products, optional):
    r = client.post("/plaid/link-token", json={"kind": kind})
    assert r.json() == {"link_token": "link-sandbox-abc"}
    body = dict(fake.requests)["/link/token/create"]
    assert body["products"] == products and body["optional_products"] == optional
    assert body["country_codes"] == ["US"]


def test_link_token_rejects_unknown_kind(client):
    assert client.post("/plaid/link-token", json={"kind": "crypto"}).status_code == 400


def test_exchange_stores_token_syncs_and_never_returns_it(client, session):
    r = client.post("/plaid/exchange", json={"public_token": "public-sandbox-1"})
    body = r.json()
    assert body["synced"] is True and body["accounts"] == 5 and body["new_transactions"] == 3
    assert body["item"]["institution"] == "Test Platypus Bank"
    assert "tok-1" not in r.text  # access token stays server-side

    items = client.get("/plaid/items")
    assert "tok-1" not in items.text
    # Times must carry a UTC offset or the browser shows them hours off.
    assert items.json()[0]["last_synced_at"].endswith("+00:00")
    assert [i["institution"] for i in items.json()] == ["Test Platypus Bank"]
    assert session.scalar(select(PlaidItem)).access_token == "tok-1"


def test_relinking_same_login_does_not_duplicate(client, session):
    client.post("/plaid/exchange", json={"public_token": "p1"})
    client.post("/plaid/exchange", json={"public_token": "p2"})
    assert len(session.scalars(select(PlaidItem)).all()) == 1


def test_sync_all_reports_each_login(client):
    client.post("/plaid/exchange", json={"public_token": "p1"})
    r = client.post("/plaid/sync").json()
    assert r["items"][0]["ok"] is True
    assert r["items"][0]["new_transactions"] == 0  # cursor saved: nothing new


def test_sync_failure_is_reported_not_crashed(session):
    broken = FakePlaid(fail={"/accounts/balance/get": "ITEM_LOGIN_REQUIRED"})
    session.add(PlaidItem(item_id="i", access_token="tok-1", institution_name="Bank"))
    session.commit()
    app.dependency_overrides[get_plaid_client] = broken.client
    with TestClient(app, base_url="http://localhost") as c:
        r = c.post("/plaid/sync").json()
    app.dependency_overrides.clear()
    assert r["items"][0] == {**r["items"][0], "ok": False, "error": "ITEM_LOGIN_REQUIRED"}


def test_unlink_revokes_at_plaid_and_forgets_token(client, fake, session):
    item_pk = client.post("/plaid/exchange", json={"public_token": "p1"}).json()["item"]["id"]
    assert client.delete(f"/plaid/items/{item_pk}").json() == {"removed": item_pk}
    assert dict(fake.requests)["/item/remove"]["access_token"] == "tok-1"
    assert session.scalars(select(PlaidItem)).all() == []
    assert client.delete(f"/plaid/items/{item_pk}").status_code == 404


def test_missing_keys_give_clear_error(session, monkeypatch):
    monkeypatch.delenv("PLAID_CLIENT_ID", raising=False)
    monkeypatch.delenv("PLAID_SECRET", raising=False)
    with TestClient(app, base_url="http://localhost") as c:
        r = c.post("/plaid/link-token", json={"kind": "banking"})
    assert r.status_code == 503 and "PLAID_CLIENT_ID" in r.json()["detail"]


def test_requests_from_other_hosts_are_rejected(session):
    # Simulates DNS rebinding: a page on evil.example pointed at this server.
    with TestClient(app, base_url="http://evil.example") as c:
        assert c.get("/summary").status_code == 400

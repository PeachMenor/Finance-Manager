"""Splitwise: who owes you and whom you owe (read-only).

Uses GET /get_friends with your personal API key
(register an app at https://secure.splitwise.com/apps to get one).
Splitwise reports each friend's balance per currency; a POSITIVE amount means
that friend owes you, which matches the app's convention.
"""

import os

import httpx

from app.integrations.base import FetchedPersonBalance
from app.services.money import to_cents

SPLITWISE_API = "https://secure.splitwise.com/api/v3.0"


class SplitwiseError(RuntimeError):
    pass


class SplitwiseClient:
    """Pass `http` in tests to fake Splitwise's responses."""

    def __init__(self, api_key: str, http: httpx.Client | None = None):
        self._http = http or httpx.Client(base_url=SPLITWISE_API, timeout=30)
        self._headers = {"Authorization": f"Bearer {api_key}"}

    @classmethod
    def from_env(cls) -> "SplitwiseClient":
        key = os.getenv("SPLITWISE_API_KEY", "")
        if not key:
            raise RuntimeError("Set SPLITWISE_API_KEY in your .env file.")
        return cls(key)

    def fetch_balances(self) -> list[FetchedPersonBalance]:
        resp = self._http.get("/get_friends", headers=self._headers)
        if resp.status_code != 200:
            raise SplitwiseError(f"Splitwise returned HTTP {resp.status_code}")
        balances = []
        for f in resp.json()["friends"]:
            name = " ".join(p for p in (f.get("first_name"), f.get("last_name")) if p) or "Friend"
            for b in f.get("balance", []):
                balances.append(
                    FetchedPersonBalance(
                        external_id=str(f["id"]),
                        name=name,
                        amount_cents=to_cents(b["amount"]),
                        currency=b["currency_code"],
                    )
                )
        return balances

"""Plaid: banks, credit cards, brokerages, retirement accounts and loans (read-only).

Talks to Plaid's REST API directly with httpx (no SDK), using:
- /accounts/balance/get        balances for every account under one login
- /institutions/get_by_id      the bank's display name
- /transactions/sync           new / changed / removed transactions since the last cursor
- /investments/holdings/get    stock and ETF positions

Sign conventions are converted to the app's:
- Plaid transaction amounts are POSITIVE for money going out; we store money out as NEGATIVE.
- Plaid credit and loan balances are already "amount owed" (positive), which matches ours.

Secrets (client id, secret, access tokens) are sent only to Plaid and never logged.
"""

import os
from datetime import date

import httpx

from app.db.models import AccountKind, DataSource
from app.integrations.base import (
    FetchedAccount,
    FetchedHolding,
    FetchedTransaction,
    Integration,
)
from app.services.money import to_cents

PLAID_HOSTS = {
    "sandbox": "https://sandbox.plaid.com",  # fake banks, fake data
    "production": "https://production.plaid.com",  # your real accounts
}

# First Platypus Bank: Plaid's standard sandbox test institution.
SANDBOX_INSTITUTION_ID = "ins_109508"

# Plaid errors meaning "this login doesn't offer that product"; skip instead of failing.
_SKIPPABLE_ERRORS = {"PRODUCTS_NOT_SUPPORTED", "PRODUCT_NOT_READY", "NO_INVESTMENT_ACCOUNTS"}

_RETIREMENT_SUBTYPES = {
    "401a", "401k", "403b", "457b", "ira", "roth", "roth 401k", "sep ira",
    "simple ira", "keogh", "pension", "retirement", "rollover ira", "thrift savings plan",
}


class PlaidError(RuntimeError):
    def __init__(self, error_code: str, message: str):
        super().__init__(f"Plaid error {error_code}: {message}")
        self.error_code = error_code


class PlaidClient:
    """Minimal Plaid API client. Pass `http` in tests to fake Plaid's responses."""

    def __init__(
        self,
        client_id: str,
        secret: str,
        env: str = "sandbox",
        http: httpx.Client | None = None,
    ):
        if env not in PLAID_HOSTS:
            raise ValueError(f"PLAID_ENV must be one of {sorted(PLAID_HOSTS)}, got {env!r}")
        self.env = env
        self._client_id = client_id
        self._secret = secret
        self._http = http or httpx.Client(base_url=PLAID_HOSTS[env], timeout=30)

    @classmethod
    def from_env(cls) -> "PlaidClient":
        client_id = os.getenv("PLAID_CLIENT_ID", "")
        secret = os.getenv("PLAID_SECRET", "")
        if not client_id or not secret:
            raise RuntimeError("Set PLAID_CLIENT_ID and PLAID_SECRET in your .env file.")
        return cls(client_id, secret, env=os.getenv("PLAID_ENV", "sandbox"))

    def post(self, path: str, body: dict) -> dict:
        payload = {"client_id": self._client_id, "secret": self._secret, **body}
        resp = self._http.post(path, json=payload)
        data = resp.json()
        if resp.status_code != 200:
            raise PlaidError(data.get("error_code", "UNKNOWN"), data.get("error_message", ""))
        return data

    # --- linking a login through Plaid Link (the secure pop-up) ---
    def create_link_token(self, kind: str = "banking") -> str:
        """Short-lived token that opens Plaid Link in the browser.

        kind="banking":     banks and cards; holdings too if the login has them.
        kind="investments": brokerages and retirement accounts that may not offer
                            transactions (otherwise Link would hide them).
        """
        if kind == "investments":
            products, optional = ["investments"], ["transactions"]
        else:
            products, optional = ["transactions"], ["investments"]
        data = self.post(
            "/link/token/create",
            {
                "client_name": "Finance Manager",
                "user": {"client_user_id": "local-user"},  # single-user local app
                "products": products,
                "optional_products": optional,
                "country_codes": ["US"],
                "language": "en",
            },
        )
        return data["link_token"]

    def exchange_public_token(self, public_token: str) -> tuple[str, str]:
        """Swap the one-time token from Link for a lasting (item_id, access_token)."""
        data = self.post("/item/public_token/exchange", {"public_token": public_token})
        return data["item_id"], data["access_token"]

    def remove_item(self, access_token: str) -> None:
        """Revoke the app's access to a login at Plaid (unlink)."""
        self.post("/item/remove", {"access_token": access_token})

    # --- sandbox only: create a fake linked login without the Link UI ---
    def create_sandbox_access_token(
        self, institution_id: str = SANDBOX_INSTITUTION_ID
    ) -> tuple[str, str]:
        """Return (item_id, access_token) for a fake login at a sandbox bank."""
        if self.env != "sandbox":
            raise RuntimeError("Sandbox logins can only be created with PLAID_ENV=sandbox.")
        public = self.post(
            "/sandbox/public_token/create",
            {"institution_id": institution_id, "initial_products": ["transactions", "investments"]},
        )
        exchanged = self.post(
            "/item/public_token/exchange", {"public_token": public["public_token"]}
        )
        return exchanged["item_id"], exchanged["access_token"]


def map_account_kind(plaid_type: str, subtype: str | None) -> AccountKind:
    """Translate Plaid's (type, subtype) into the app's AccountKind."""
    subtype = (subtype or "").lower()
    if plaid_type == "depository":
        if subtype == "checking":
            return AccountKind.CHECKING
        if subtype == "hsa":
            return AccountKind.HSA
        return AccountKind.SAVINGS  # savings, money market, CD, cash management...
    if plaid_type == "credit":
        return AccountKind.CREDIT_CARD
    if plaid_type == "loan":
        return AccountKind.LOAN
    if plaid_type == "investment":
        if "crypto" in subtype:  # e.g. "crypto exchange"
            return AccountKind.CRYPTO
        if subtype == "hsa":
            return AccountKind.HSA
        if subtype in _RETIREMENT_SUBTYPES:
            return AccountKind.RETIREMENT
        return AccountKind.BROKERAGE
    return AccountKind.OTHER


# Names that say only what kind of account it is, not which one.
_GENERIC_NAMES = {
    "account", "brokerage", "checking", "credit", "credit card", "investment",
    "investments", "loan", "savings",
}


def account_display_name(a: dict) -> str:
    """Pick the more specific of Plaid's two names.

    Institutions differ: some send a generic `name` ("CREDIT CARD") with a
    specific `official_name` ("Rewards Visa"); others the reverse (`name` "RSU",
    `official_name` "Investment"). Prefer `official_name` unless it's generic.
    Capitalization is kept as sent, so acronyms like "ESPP" stay intact.
    """
    official = (a.get("official_name") or "").strip()
    name = (a.get("name") or "").strip()
    if official and official.lower() not in _GENERIC_NAMES:
        return official
    return name or official or "Account"


class PlaidIntegration(Integration):
    """Reads one linked Plaid login. After `fetch_accounts`, save `next_cursor`."""

    source = DataSource.PLAID

    def __init__(self, client: PlaidClient, access_token: str, cursor: str | None = None):
        self._client = client
        self._token = access_token
        self.next_cursor = cursor
        self.institution_name: str | None = None

    def _call(self, path: str, body: dict | None = None) -> dict | None:
        """Call Plaid; return None when the login simply lacks that product."""
        try:
            return self._client.post(path, {"access_token": self._token, **(body or {})})
        except PlaidError as e:
            if e.error_code in _SKIPPABLE_ERRORS:
                return None
            raise

    def _institution(self, institution_id: str | None) -> str:
        if not institution_id:
            return "Unknown institution"
        data = self._client.post(
            "/institutions/get_by_id",
            {"institution_id": institution_id, "country_codes": ["US"]},
        )
        return data["institution"]["name"]

    def _transactions(self) -> tuple[dict[str, list[FetchedTransaction]], dict[str, list[str]]]:
        """Page through /transactions/sync. Returns (changed by account, removed ids by account)."""
        changed: dict[str, list[FetchedTransaction]] = {}
        removed: dict[str, list[str]] = {}
        cursor = self.next_cursor
        while True:
            body = {"count": 500}
            if cursor:
                body["cursor"] = cursor
            page = self._call("/transactions/sync", body)
            if page is None:  # login has no transactions product (e.g. investment-only)
                break
            for t in page["added"] + page["modified"]:
                if t.get("pending"):
                    continue  # wait until it posts; avoids double-counting
                changed.setdefault(t["account_id"], []).append(
                    FetchedTransaction(
                        external_id=t["transaction_id"],
                        posted_on=date.fromisoformat(t["date"]),
                        amount_cents=-to_cents(t["amount"]),  # Plaid: + is money out
                        description=t.get("merchant_name") or t.get("name") or "",
                    )
                )
            for r in page["removed"]:
                removed.setdefault(r.get("account_id", ""), []).append(r["transaction_id"])
            cursor = page["next_cursor"]
            if not page["has_more"]:
                break
        self.next_cursor = cursor
        return changed, removed

    def _holdings(self) -> dict[str, list[FetchedHolding]]:
        data = self._call("/investments/holdings/get")
        if data is None:
            return {}
        tickers = {
            s["security_id"]: (s.get("ticker_symbol") or s.get("name") or "UNKNOWN")[:20]
            for s in data["securities"]
        }
        by_account: dict[str, list[FetchedHolding]] = {}
        for h in data["holdings"]:
            basis = h.get("cost_basis")
            by_account.setdefault(h["account_id"], []).append(
                FetchedHolding(
                    symbol=tickers.get(h["security_id"], "UNKNOWN"),
                    quantity=float(h["quantity"]),
                    cost_basis_cents=to_cents(basis) if basis is not None else None,
                )
            )
        return by_account

    def fetch_accounts(self, since: date | None = None) -> list[FetchedAccount]:
        balances = self._client.post("/accounts/balance/get", {"access_token": self._token})
        self.institution_name = self._institution(balances["item"].get("institution_id"))
        changed, removed = self._transactions()
        has_investments = any(a["type"] == "investment" for a in balances["accounts"])
        holdings = self._holdings() if has_investments else {}

        accounts = []
        for a in balances["accounts"]:
            bal = a["balances"]
            current = bal["current"] if bal.get("current") is not None else bal.get("available")
            kind = map_account_kind(a["type"], a.get("subtype"))
            txns = changed.get(a["account_id"], [])
            if since:
                txns = [t for t in txns if t.posted_on >= since]
            accounts.append(
                FetchedAccount(
                    external_id=a["account_id"],
                    institution_name=self.institution_name,
                    name=account_display_name(a),
                    kind=kind,
                    balance_cents=to_cents(current or 0),
                    currency=bal.get("iso_currency_code") or "USD",
                    mask=(a.get("mask") or None),
                    transactions=txns,
                    removed_transaction_ids=removed.get(a["account_id"], []),
                    holdings=holdings.get(a["account_id"], [])
                    if a["type"] == "investment"
                    else None,
                )
            )
        return accounts

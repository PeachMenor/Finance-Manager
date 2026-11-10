"""A fake Plaid server for tests. Responses follow the shape of Plaid's real API.

Fake bank "Test Platypus Bank" with one login holding:
    checking     $1,100.00
    savings      $2,500.50
    credit card  $410.25 owed
    401k         $23,631.98  (holdings: 50 VOO, $1,000 cash)
    auto loan    $12,000.00 owed
"""

import json

import httpx

ACCOUNTS = [
    {"account_id": "chk", "name": "Plaid Checking", "type": "depository", "subtype": "checking",
     "balances": {"current": 1100.00, "available": 1000.00, "iso_currency_code": "USD"}},
    {"account_id": "sav", "name": "Plaid Saving", "type": "depository", "subtype": "savings",
     "balances": {"current": None, "available": 2500.50, "iso_currency_code": "USD"}},
    {"account_id": "cc", "name": "Plaid Credit Card", "type": "credit", "subtype": "credit card",
     "balances": {"current": 410.25, "available": 4589.75, "iso_currency_code": "USD"}},
    {"account_id": "401k", "name": "Plaid 401k", "type": "investment", "subtype": "401k",
     "balances": {"current": 23631.98, "available": None, "iso_currency_code": "USD"}},
    {"account_id": "auto", "name": "Plaid Auto Loan", "type": "loan", "subtype": "auto",
     "balances": {"current": 12000.00, "available": None, "iso_currency_code": "USD"}},
]

# Two pages of /transactions/sync to exercise pagination.
SYNC_PAGES = {
    None: {
        "added": [
            {"transaction_id": "t-coffee", "account_id": "chk", "date": "2026-11-02",
             "amount": 4.33, "name": "STARBUCKS #123", "merchant_name": "Starbucks", "pending": False},
            {"transaction_id": "t-pending", "account_id": "chk", "date": "2026-11-03",
             "amount": 99.00, "name": "PENDING CHARGE", "pending": True},
            {"transaction_id": "t-dinner", "account_id": "cc", "date": "2026-11-02",
             "amount": 64.10, "name": "Dinner", "merchant_name": None, "pending": False},
        ],
        "modified": [], "removed": [], "next_cursor": "c1", "has_more": True,
    },
    "c1": {
        "added": [
            {"transaction_id": "t-pay", "account_id": "chk", "date": "2026-11-01",
             "amount": -2500.00, "name": "PAYROLL", "merchant_name": None, "pending": False},
        ],
        "modified": [],
        "removed": [{"transaction_id": "t-old", "account_id": "chk"}],
        "next_cursor": "c2", "has_more": False,
    },
    "c2": {"added": [], "modified": [], "removed": [], "next_cursor": "c2", "has_more": False},
}

HOLDINGS = {
    "holdings": [
        {"account_id": "401k", "security_id": "s-voo", "quantity": 50.0, "cost_basis": 20000.00},
        {"account_id": "401k", "security_id": "s-cash", "quantity": 1000.0, "cost_basis": None},
    ],
    "securities": [
        {"security_id": "s-voo", "ticker_symbol": "VOO", "name": "Vanguard S&P 500 ETF"},
        {"security_id": "s-cash", "ticker_symbol": None, "name": "Cash"},
    ],
}


class FakePlaid:
    """Records every request; `fail` maps a path to a Plaid error code to return."""

    def __init__(self, fail: dict[str, str] | None = None):
        self.requests: list[tuple[str, dict]] = []
        self.fail = fail or {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content)
        self.requests.append((path, body))
        if path in self.fail:
            return httpx.Response(400, json={"error_code": self.fail[path], "error_message": "nope"})
        if path == "/accounts/balance/get":
            return httpx.Response(200, json={"accounts": ACCOUNTS, "item": {"institution_id": "ins_test"}})
        if path == "/institutions/get_by_id":
            return httpx.Response(200, json={"institution": {"name": "Test Platypus Bank"}})
        if path == "/transactions/sync":
            return httpx.Response(200, json=SYNC_PAGES[body.get("cursor")])
        if path == "/investments/holdings/get":
            return httpx.Response(200, json=HOLDINGS)
        return httpx.Response(404, json={"error_code": "NOT_FOUND", "error_message": path})

    def client(self):
        from app.integrations.plaid import PlaidClient

        http = httpx.Client(transport=httpx.MockTransport(self.handler), base_url="https://sandbox.plaid.com")
        return PlaidClient("cid", "sec", env="sandbox", http=http)

"""Fake bank data for demos and tests. No network, no keys, nothing real.

The numbers are chosen so the expected net worth is easy to check by hand:

    Assets:       2,500.00 checking + 10,000.00 savings + 5,000.00 brokerage
                  + 20,000.00 401k + 1,200.00 HSA                = 38,700.00
    Liabilities:  750.25 credit card + 15,000.00 car loan        = 15,750.25
    Splitwise:    Alex owes you 40.00, you owe Sam 25.50         = +14.50
    Net worth:    38,700.00 − 15,750.25 + 14.50                  = 22,964.25
"""

from datetime import date

from app.db.models import AccountKind, DataSource
from app.integrations.base import (
    FetchedAccount,
    FetchedHolding,
    FetchedPersonBalance,
    FetchedTransaction,
    Integration,
)

EXPECTED_NET_WORTH_CENTS = 2_296_425


class DemoBankIntegration(Integration):
    source = DataSource.MANUAL  # tagged manual so it never mixes with real Plaid rows

    def fetch_accounts(self, since: date | None = None) -> list[FetchedAccount]:
        d = date(2026, 11, 1)
        return [
            FetchedAccount(
                external_id="demo-checking",
                institution_name="Demo Bank",
                name="Demo Checking",
                kind=AccountKind.CHECKING,
                balance_cents=2_500_00,
                transactions=[
                    FetchedTransaction("demo-t1", d, 4_000_00, "Salary"),
                    FetchedTransaction("demo-t2", d, -1_800_00, "Rent"),
                    FetchedTransaction("demo-t3", d, -54_37, "Groceries"),
                ],
            ),
            FetchedAccount(
                external_id="demo-savings",
                institution_name="Demo Bank",
                name="Demo High-Yield Savings",
                kind=AccountKind.SAVINGS,
                balance_cents=10_000_00,
            ),
            FetchedAccount(
                external_id="demo-card",
                institution_name="Demo Card Co",
                name="Demo Rewards Card",
                kind=AccountKind.CREDIT_CARD,
                balance_cents=750_25,  # amount owed
                transactions=[FetchedTransaction("demo-t4", d, -120_00, "Dinner")],
            ),
            FetchedAccount(
                external_id="demo-brokerage",
                institution_name="Demo Brokerage",
                name="Demo Individual",
                kind=AccountKind.BROKERAGE,
                balance_cents=5_000_00,
                holdings=[
                    FetchedHolding("VOO", 5.0, 2_000_00),
                    FetchedHolding("AAPL", 8.5, 1_500_00),
                ],
            ),
            FetchedAccount(
                external_id="demo-401k",
                institution_name="Demo Brokerage",
                name="Demo 401k",
                kind=AccountKind.RETIREMENT,
                balance_cents=20_000_00,
                holdings=[FetchedHolding("VTI", 70.0, 15_000_00)],
            ),
            FetchedAccount(
                external_id="demo-hsa",
                institution_name="Demo Brokerage",
                name="Demo HSA",
                kind=AccountKind.HSA,
                balance_cents=1_200_00,
            ),
            FetchedAccount(
                external_id="demo-car-loan",
                institution_name="Demo Auto Finance",
                name="Demo Car Loan",
                kind=AccountKind.LOAN,
                balance_cents=15_000_00,  # amount owed
            ),
        ]


DEMO_PEOPLE = [
    FetchedPersonBalance("demo-alex", "Alex", 40_00),  # Alex owes you
    FetchedPersonBalance("demo-sam", "Sam", -25_50),  # you owe Sam
    FetchedPersonBalance("demo-kim", "Kim", 0),  # settled up: should be dropped
]

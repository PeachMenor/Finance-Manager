"""The common shape every data source returns.

Each provider (Plaid, SimpleFIN, statement import, ...) converts its own API format
into these plain records. The sync code (`app.services.sync`) then writes them to
the database the same way regardless of where they came from, so adding a
provider never touches the rest of the app.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

from app.db.models import AccountKind, DataSource


@dataclass
class FetchedTransaction:
    external_id: str
    posted_on: date
    amount_cents: int  # negative = money out, positive = money in
    description: str
    category: str | None = None  # provider's primary category, e.g. "FOOD_AND_DRINK"
    category_detailed: str | None = None  # e.g. "FOOD_AND_DRINK_GROCERIES"


@dataclass
class FetchedHolding:
    symbol: str
    quantity: float
    cost_basis_cents: int | None = None


@dataclass
class FetchedAccount:
    external_id: str
    institution_name: str
    name: str
    kind: AccountKind
    balance_cents: int  # liabilities as positive amounts owed
    currency: str = "USD"
    mask: str | None = None  # last 4 digits, if the provider gives them
    # New or changed transactions. Re-sending one already stored updates it.
    transactions: list[FetchedTransaction] = field(default_factory=list)
    # Transactions the provider says no longer exist (e.g. a pending charge that dropped).
    removed_transaction_ids: list[str] = field(default_factory=list)
    # None = this provider doesn't report holdings, so keep what's stored.
    # [] = it reports holdings and there are none.
    holdings: list[FetchedHolding] | None = None


@dataclass
class FetchedPersonBalance:
    """A shared-expense balance with one person. Positive = they owe you."""

    external_id: str
    name: str
    amount_cents: int
    currency: str = "USD"


class Integration(ABC):
    """Interface for a read-only source of accounts."""

    #: Which `DataSource` value records from this integration are tagged with.
    source: DataSource

    @abstractmethod
    def fetch_accounts(self, since: date | None = None) -> list[FetchedAccount]:
        """Return all accounts with balances, plus transactions posted on/after `since`."""

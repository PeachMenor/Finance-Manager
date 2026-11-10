"""The common shape every data source returns.

Each provider (SimpleFIN, Plaid, CSV import, ...) converts its own API format
into these plain records. The sync code then writes them to the database the
same way regardless of where they came from, so adding a provider never
touches the rest of the app.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

from app.db.models import AccountKind, DataSource


@dataclass
class FetchedTransaction:
    external_id: str
    posted_on: date
    amount_cents: int  # negative = money out
    description: str


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
    transactions: list[FetchedTransaction] = field(default_factory=list)
    holdings: list[FetchedHolding] = field(default_factory=list)


class Integration(ABC):
    """Interface for a read-only data source."""

    #: Which `DataSource` value records from this integration are tagged with.
    source: DataSource

    @abstractmethod
    def fetch_accounts(self, since: date | None = None) -> list[FetchedAccount]:
        """Return all accounts with balances, plus transactions posted on/after `since`."""

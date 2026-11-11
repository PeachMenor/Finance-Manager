"""Database tables.

Conventions:
- Money is stored as integer **cents** (`*_cents` columns) to avoid floating-point
  rounding errors when summing balances. Convert with `app.services.money`.
- Liabilities (credit cards, loans) are stored as POSITIVE balances; the account
  `kind` decides whether it adds to or subtracts from net worth.
- `source` + `external_id` identify a record in the provider it came from
  (SimpleFIN, Plaid, CSV...), so re-syncing updates rows instead of duplicating them.
"""

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AccountKind(str, enum.Enum):
    """What type of account it is. Drives net-worth math and dashboard grouping."""

    CHECKING = "checking"
    SAVINGS = "savings"
    CREDIT_CARD = "credit_card"
    BROKERAGE = "brokerage"
    RETIREMENT = "retirement"  # 401k, IRA, ...
    HSA = "hsa"  # health savings account (cash or invested)
    LOAN = "loan"
    CASH = "cash"
    CRYPTO = "crypto"
    OTHER = "other"

    @property
    def is_liability(self) -> bool:
        return self in (AccountKind.CREDIT_CARD, AccountKind.LOAN)


class DataSource(str, enum.Enum):
    """Where a record came from."""

    SIMPLEFIN = "simplefin"
    PLAID = "plaid"
    SPLITWISE = "splitwise"
    CSV = "csv"
    MANUAL = "manual"


class BudgetPeriod(str, enum.Enum):
    MONTHLY = "monthly"
    ANNUAL = "annual"


class Institution(Base):
    """A bank, card issuer or brokerage (e.g. "Example Bank")."""

    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)

    accounts: Mapped[list["Account"]] = relationship(back_populates="institution")


class Account(Base):
    """One account at an institution. Never stores full account numbers."""

    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"))
    name: Mapped[str] = mapped_column(String(120))  # from the provider, e.g. "Rewards Visa"
    # Your own label; set once with `python -m app.cli rename`, never overwritten by sync.
    nickname: Mapped[str | None] = mapped_column(String(120))
    # Last 4 digits only, to tell similar accounts apart. Full numbers are never stored.
    mask: Mapped[str | None] = mapped_column(String(4))
    kind: Mapped[AccountKind] = mapped_column(Enum(AccountKind))
    source: Mapped[DataSource] = mapped_column(Enum(DataSource))
    external_id: Mapped[str] = mapped_column(String(200))  # provider's id, not the account number
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    # Latest known balance; full history lives in BalanceSnapshot.
    balance_cents: Mapped[int] = mapped_column(Integer, default=0)
    balance_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # False for things you track but don't own yet (e.g. unvested RSUs).
    include_in_net_worth: Mapped[bool] = mapped_column(Boolean, default=True)
    # Hidden accounts are left off dashboard lists but STILL count toward net worth,
    # so money landing in one later is never silently dropped. Sync keeps them updated.
    hidden: Mapped[bool | None] = mapped_column(Boolean, default=False)

    institution: Mapped[Institution | None] = relationship(back_populates="accounts")
    snapshots: Mapped[list["BalanceSnapshot"]] = relationship(back_populates="account")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")
    holdings: Mapped[list["Holding"]] = relationship(back_populates="account")

    @property
    def display_name(self) -> str:
        """What the dashboard shows, e.g. "Travel Card ••1234"."""
        base = self.nickname or self.name
        return f"{base} ••{self.mask}" if self.mask else base


class BalanceSnapshot(Base):
    """A balance at a point in time; powers the net-worth history chart."""

    __tablename__ = "balance_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    balance_cents: Mapped[int] = mapped_column(Integer)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    account: Mapped[Account] = relationship(back_populates="snapshots")


class Transaction(Base):
    """A single money movement. Negative amount = money out, positive = money in."""

    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("account_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    external_id: Mapped[str] = mapped_column(String(200))
    posted_on: Mapped[date] = mapped_column(Date)
    amount_cents: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(300))
    category: Mapped[str | None] = mapped_column(String(80))  # your own override (Stage 3)
    note: Mapped[str | None] = mapped_column(String(300))  # your own note, e.g. what a charge was for
    # Your own split of one payment across categories, JSON {"Rent": 100000, "Education": 50000}
    # in cents of money out; must add up to the payment. Overrides `category`.
    split_parts: Mapped[str | None] = mapped_column(String(500))

    def parts(self) -> dict[str, int] | None:
        if not self.split_parts:
            return None
        import json

        return {k: int(v) for k, v in json.loads(self.split_parts).items()}
    # The provider's category, e.g. Plaid primary "FOOD_AND_DRINK", detailed
    # "FOOD_AND_DRINK_GROCERIES". Refreshed on every sync; never overrides `category`.
    provider_category: Mapped[str | None] = mapped_column(String(80))
    provider_category_detailed: Mapped[str | None] = mapped_column(String(120))

    account: Mapped[Account] = relationship(back_populates="transactions")


class Holding(Base):
    """A stock/ETF position inside a brokerage or retirement account."""

    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("account_id", "symbol"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    symbol: Mapped[str] = mapped_column(String(20))  # e.g. "VOO"
    # Shares can be fractional; float precision is fine for share counts.
    quantity: Mapped[float] = mapped_column(Float)
    cost_basis_cents: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    account: Mapped[Account] = relationship(back_populates="holdings")


class Budget(Base):
    """A spending limit for a category, monthly or for the whole year."""

    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("category", "period", "year"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(80))
    period: Mapped[BudgetPeriod] = mapped_column(Enum(BudgetPeriod))
    year: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)


class PersonBalance(Base):
    """What one person owes you, or you owe them (from Splitwise).

    Positive amount = they owe you. Negative = you owe them.
    One row per person per currency. Replaced wholesale on each sync, so people
    you've settled up with disappear.
    """

    __tablename__ = "person_balances"
    __table_args__ = (UniqueConstraint("source", "external_id", "currency"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[DataSource] = mapped_column(Enum(DataSource))
    external_id: Mapped[str] = mapped_column(String(100))  # provider's person id
    name: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    amount_cents: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PlaidItem(Base):
    """One linked Plaid login (an "Item"). One login can hold several accounts.

    `access_token` is a secret: it lets the app read this login's data. It lives
    only in this local, git-ignored database and is never logged or returned by the API.
    `cursor` remembers how far transaction sync has got, so each sync only fetches changes.
    """

    __tablename__ = "plaid_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[str] = mapped_column(String(100), unique=True)
    access_token: Mapped[str] = mapped_column(String(200))
    institution_name: Mapped[str | None] = mapped_column(String(120))
    cursor: Mapped[str | None] = mapped_column(String(500))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoanTerms(Base):
    """Terms for a loan entered by hand (no bank connection).

    The balance is known exactly on `balance_as_of` (from a statement). After that
    the app estimates it by applying each monthly payment: interest for the month
    is charged first, the rest of the payment reduces the principal. Entering a
    newer statement resets the estimate to the exact figure.
    """

    __tablename__ = "loan_terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), unique=True)
    principal_cents: Mapped[int] = mapped_column(Integer)  # owed on balance_as_of
    balance_as_of: Mapped[date] = mapped_column(Date)
    apr_bps: Mapped[int] = mapped_column(Integer)  # 5.49% APR -> 549 basis points
    monthly_payment_cents: Mapped[int] = mapped_column(Integer)
    payment_day: Mapped[int] = mapped_column(Integer)  # day of month payments post (1-28)
    maturity_date: Mapped[date | None] = mapped_column(Date)
    # Optional: text that identifies payments to this lender in your bank transactions
    # (e.g. "Example Auto Finance"). When set, the balance follows the payments you
    # actually made, with daily interest, instead of assuming one payment a month.
    payment_match: Mapped[str | None] = mapped_column(String(120))
    # Days between the lender crediting a payment and your bank posting it
    # (e.g. credited Nov 2, shows in the bank Nov 3 -> 1).
    posting_lag_days: Mapped[int | None] = mapped_column(Integer)
    # Interest already accrued but not yet paid on `balance_as_of` (e.g. after a
    # principal-only payment). The next payment covers it before any principal.
    unpaid_interest_cents: Mapped[int | None] = mapped_column(Integer)

    account: Mapped[Account] = relationship()


class SplitExpense(Base):
    """One shared expense from Splitwise, with YOUR part of it.

    - you_paid_cents: what left your accounts for it (0 if someone else paid)
    - share_cents:    your share of the cost, i.e. your real spending
    Settle-ups ("A paid B") are not stored here: they're repayments, not spending.
    Replaced wholesale on each import.
    """

    __tablename__ = "split_expenses"
    __table_args__ = (UniqueConstraint("external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(300))  # group|date|description|cost
    spent_on: Mapped[date] = mapped_column(Date)
    group_name: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(300))
    cost_cents: Mapped[int] = mapped_column(Integer)
    you_paid_cents: Mapped[int] = mapped_column(Integer)
    share_cents: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(80))
    # Optional split of your share across categories, as JSON {"Rent": 90000, ...}
    # (e.g. one rent payment that also covers utilities). Must add up to share_cents.
    split_parts: Mapped[str | None] = mapped_column(String(500))

    def parts(self) -> dict[str, int]:
        """Your share by category (the whole share in `category` unless split)."""
        if self.split_parts:
            import json

            return {k: int(v) for k, v in json.loads(self.split_parts).items()}
        return {self.category: self.share_cents}


class ManualRecurring(Base):
    """A monthly bill entered by hand, e.g. your share of a plan someone else pays."""

    __tablename__ = "manual_recurring"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer)  # per month, your share
    category: Mapped[str] = mapped_column(String(80))
    day_of_month: Mapped[int | None] = mapped_column(Integer)
    paid_via: Mapped[str | None] = mapped_column(String(120))  # e.g. "Splitwise"
    note: Mapped[str | None] = mapped_column(String(300))
    # Non-monthly bills (tuition, insurance renewals...): how often, and when next.
    cadence: Mapped[str | None] = mapped_column(String(20))  # monthly (default) | quarterly | semester | yearly
    next_due: Mapped[date | None] = mapped_column(Date)  # earliest expected date
    due_note: Mapped[str | None] = mapped_column(String(120))  # e.g. "Dec or Jan"

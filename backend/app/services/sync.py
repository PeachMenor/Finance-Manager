"""Write data fetched from any provider into the database.

Every sync is safe to repeat: accounts are matched on (source, external_id) and
transactions on (account, external_id), so running it twice never duplicates rows.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    BalanceSnapshot,
    DataSource,
    Holding,
    Institution,
    PersonBalance,
    PlaidItem,
    Transaction,
)
from app.integrations.base import FetchedAccount, FetchedPersonBalance


@dataclass
class SyncResult:
    accounts: int = 0
    new_transactions: int = 0
    updated_transactions: int = 0
    removed_transactions: int = 0

    def __iadd__(self, other: "SyncResult") -> "SyncResult":
        self.accounts += other.accounts
        self.new_transactions += other.new_transactions
        self.updated_transactions += other.updated_transactions
        self.removed_transactions += other.removed_transactions
        return self


def _get_or_create_institution(session: Session, name: str) -> Institution:
    inst = session.scalar(select(Institution).where(Institution.name == name))
    if inst is None:
        inst = Institution(name=name)
        session.add(inst)
    return inst


def sync_accounts(
    session: Session,
    source: DataSource,
    fetched: list[FetchedAccount],
    now: datetime | None = None,
) -> SyncResult:
    """Upsert accounts, record a balance snapshot, and apply transaction/holding changes."""
    now = now or datetime.now(timezone.utc)
    result = SyncResult()

    for fa in fetched:
        # Look up the institution BEFORE adding a new account: the query can trigger
        # an automatic flush, which would try to insert a half-filled account row.
        institution = _get_or_create_institution(session, fa.institution_name)
        acct = session.scalar(
            select(Account).where(Account.source == source, Account.external_id == fa.external_id)
        )
        if acct is None:
            acct = Account(source=source, external_id=fa.external_id)
            session.add(acct)

        acct.institution = institution
        acct.name = fa.name
        acct.kind = fa.kind
        acct.currency = fa.currency
        acct.balance_cents = fa.balance_cents
        acct.balance_updated_at = now
        session.add(BalanceSnapshot(account=acct, balance_cents=fa.balance_cents, taken_at=now))
        session.flush()  # assigns acct.id for the queries below
        result.accounts += 1

        # --- transactions: insert new, update changed ---
        ids = [t.external_id for t in fa.transactions]
        existing = {
            t.external_id: t
            for t in session.scalars(
                select(Transaction).where(
                    Transaction.account_id == acct.id, Transaction.external_id.in_(ids)
                )
            )
        }
        for ft in fa.transactions:
            row = existing.get(ft.external_id)
            if row is None:
                session.add(
                    Transaction(
                        account_id=acct.id,
                        external_id=ft.external_id,
                        posted_on=ft.posted_on,
                        amount_cents=ft.amount_cents,
                        description=ft.description,
                    )
                )
                result.new_transactions += 1
            else:
                # Keep the user's category; refresh only what the bank can change.
                row.posted_on = ft.posted_on
                row.amount_cents = ft.amount_cents
                row.description = ft.description
                result.updated_transactions += 1

        # --- transactions the provider removed ---
        if fa.removed_transaction_ids:
            removed = session.execute(
                delete(Transaction).where(
                    Transaction.account_id == acct.id,
                    Transaction.external_id.in_(fa.removed_transaction_ids),
                )
            )
            result.removed_transactions += removed.rowcount

        # --- holdings: provider gives the full current list, so replace ---
        if fa.holdings is not None:
            session.execute(delete(Holding).where(Holding.account_id == acct.id))
            for fh in fa.holdings:
                session.add(
                    Holding(
                        account_id=acct.id,
                        symbol=fh.symbol,
                        quantity=fh.quantity,
                        cost_basis_cents=fh.cost_basis_cents,
                        updated_at=now,
                    )
                )

    session.commit()
    return result


def sync_person_balances(
    session: Session, source: DataSource, balances: list[FetchedPersonBalance]
) -> int:
    """Replace all balances from `source` with the latest list. Zero balances are dropped."""
    session.execute(delete(PersonBalance).where(PersonBalance.source == source))
    kept = [b for b in balances if b.amount_cents != 0]
    for b in kept:
        session.add(
            PersonBalance(
                source=source,
                external_id=b.external_id,
                name=b.name,
                currency=b.currency,
                amount_cents=b.amount_cents,
            )
        )
    session.commit()
    return len(kept)


def sync_plaid_items(session: Session, client) -> SyncResult:
    """Sync every linked Plaid login, saving each one's cursor for the next run."""
    from app.integrations.plaid import PlaidIntegration  # local import avoids a cycle

    total = SyncResult()
    for item in session.scalars(select(PlaidItem)).all():
        integration = PlaidIntegration(client, item.access_token, cursor=item.cursor)
        total += sync_accounts(session, DataSource.PLAID, integration.fetch_accounts())
        item.cursor = integration.next_cursor
        item.institution_name = integration.institution_name
        item.last_synced_at = datetime.now(timezone.utc)
        session.commit()
    return total

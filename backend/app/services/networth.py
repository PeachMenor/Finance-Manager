"""Net worth: what you own minus what you owe.

    net worth = assets (bank, savings, investments, HSA, cash)
              − liabilities (credit cards, loans)
              + owed to you (Splitwise)
              − you owe (Splitwise)

Accounts marked `include_in_net_worth = False` (e.g. unvested RSUs) are reported
separately as `excluded_cents` and not added in.

Only amounts in `currency` (USD by default) are summed; mixing currencies needs
exchange rates, which aren't part of Phase 1.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Account, PersonBalance


@dataclass
class AccountLine:
    name: str
    institution: str | None
    kind: str
    balance_cents: int
    is_liability: bool
    included: bool
    hidden: bool = False  # left off lists, still counted


@dataclass
class NetWorthSummary:
    assets_cents: int = 0
    liabilities_cents: int = 0
    owed_to_you_cents: int = 0
    you_owe_cents: int = 0
    excluded_cents: int = 0
    accounts: list[AccountLine] = field(default_factory=list)
    people: list[tuple[str, int]] = field(default_factory=list)  # (name, +owes you / −you owe)

    @property
    def net_worth_cents(self) -> int:
        return (
            self.assets_cents
            - self.liabilities_cents
            + self.owed_to_you_cents
            - self.you_owe_cents
        )


def compute_net_worth(session: Session, currency: str = "USD") -> NetWorthSummary:
    summary = NetWorthSummary()

    accounts = session.scalars(
        select(Account).where(Account.currency == currency).order_by(Account.name)
    ).all()
    for a in accounts:
        liability = a.kind.is_liability
        summary.accounts.append(
            AccountLine(
                name=a.display_name,
                institution=a.institution.name if a.institution else None,
                kind=a.kind.value,
                balance_cents=a.balance_cents,
                is_liability=liability,
                included=a.include_in_net_worth,
                hidden=bool(a.hidden),
            )
        )
        if not a.include_in_net_worth:
            summary.excluded_cents += a.balance_cents
        elif liability:
            summary.liabilities_cents += a.balance_cents
        else:
            summary.assets_cents += a.balance_cents

    people = session.scalars(
        select(PersonBalance)
        .where(PersonBalance.currency == currency)
        .order_by(PersonBalance.name)
    ).all()
    for p in people:
        summary.people.append((p.name, p.amount_cents))
        if p.amount_cents > 0:
            summary.owed_to_you_cents += p.amount_cents
        else:
            summary.you_owe_cents += -p.amount_cents

    return summary

"""Recurring monthly bills and subscriptions.

Two sources:

1. Detected from your transactions. For each merchant, charges are chained into
   a series when the next one comes 25-35 days after the previous and its amount
   is within 25%. A series counts as a recurring bill only if it looks like a
   subscription, not a shopping habit:
   - every step between charges is within 1%, except at most one price change
     (e.g. 9.99 -> 11.99), and at least one step is a steady repeat;
   - in habit categories (Food, Shopping, Transport) it needs 3+ months in a row,
     elsewhere 2+.
   One-off purchases at the same merchant (tickets, orders) don't chain.

2. Added by hand (`ManualRecurring`), for bills that never hit your accounts,
   e.g. your share of a phone plan someone else pays via Splitwise.

If a charge was split on Splitwise, the bill shows your share.

Optional private labels (data/recurring_labels.json, git-ignored) give series
friendlier names, e.g. {"merchant": "StreamCo", "max": 5, "label": "Basic plan"}.
"""

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ManualRecurring, Transaction
from app.services.spending import classify, match_split_expenses

MIN_GAP_DAYS, MAX_GAP_DAYS = 25, 35
MAX_PRICE_CHANGE = 0.25  # chaining tolerance
STEADY = 0.01            # a "same price" step: within 1%
HABIT_CATEGORIES = {"Food", "Shopping", "Transport"}
ACTIVE_WITHIN_DAYS = 40  # a monthly bill not seen for longer is shown as possibly cancelled


@dataclass
class RecurringBill:
    name: str
    merchant: str
    category: str
    amount_cents: int  # latest amount (your share if split)
    last_charged: date | None
    next_expected: date | None
    account: str | None
    source: str  # "detected" | "manual"
    active: bool = True
    charges: list[tuple[date, int]] = field(default_factory=list)
    note: str = ""


def _add_month(d: date) -> date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    return date(y, m, 28)


def _looks_like_subscription(s: list[Transaction]) -> bool:
    amounts = [-t.amount_cents for t in s]
    steps = [abs(b - a) / max(a, 1) for a, b in zip(amounts, amounts[1:])]
    steady = sum(1 for x in steps if x <= STEADY)
    changes = len(steps) - steady
    if not steps or steady == 0 or changes > 1:
        return False
    first = s[-1]
    category = classify(first.provider_category, first.provider_category_detailed,
                        first.amount_cents, first.category).category
    return len(s) >= (3 if category in HABIT_CATEGORIES else 2)


def load_labels(path: Path | None) -> list[dict]:
    if path and path.exists():
        return json.loads(path.read_text()).get("labels", [])
    return []


def _label(merchant: str, amount_cents: int, labels: list[dict]) -> str:
    for rule in labels:
        if rule.get("merchant", "").lower() != merchant.lower():
            continue
        amt = amount_cents / 100
        if "min" in rule and amt < rule["min"]:
            continue
        if "max" in rule and amt > rule["max"]:
            continue
        return rule["label"]
    return merchant


def detect_recurring(session: Session, today: date | None = None,
                     labels_path: Path | None = None) -> list[RecurringBill]:
    today = today or date.today()
    labels = load_labels(labels_path)
    share_by_txn = {m.transaction.id: m.expense.share_cents
                    for m in match_split_expenses(session) if m.transaction is not None}

    by_merchant: dict[str, list[Transaction]] = {}
    for t in session.scalars(select(Transaction).where(Transaction.amount_cents < 0).order_by(Transaction.posted_on)):
        c = classify(t.provider_category, t.provider_category_detailed, t.amount_cents, t.category)
        if c.kind != "spending" or c.category == "Rent":  # rent is tracked on its own
            continue
        by_merchant.setdefault(t.description.strip(), []).append(t)

    bills = []
    for merchant, txns in by_merchant.items():
        series: list[list[Transaction]] = []
        for t in txns:
            amount = -t.amount_cents
            for s in series:
                last = s[-1]
                gap = (t.posted_on - last.posted_on).days
                change = abs(amount - (-last.amount_cents)) / max(-last.amount_cents, 1)
                if MIN_GAP_DAYS <= gap <= MAX_GAP_DAYS and change <= MAX_PRICE_CHANGE:
                    s.append(t)
                    break
            else:
                series.append([t])
        for s in series:
            if not _looks_like_subscription(s):
                continue
            last = s[-1]
            amount = share_by_txn.get(last.id, -last.amount_cents)
            c = classify(last.provider_category, last.provider_category_detailed, last.amount_cents, last.category)
            changed = -s[-1].amount_cents != -s[0].amount_cents
            notes = []
            if last.id in share_by_txn:
                notes.append(f"your share of {-last.amount_cents / 100:.2f}")
            if changed:
                notes.append(f"was {-s[0].amount_cents / 100:.2f}")
            active = (today - last.posted_on).days <= ACTIVE_WITHIN_DAYS
            bills.append(RecurringBill(
                name=_label(merchant, -last.amount_cents, labels),
                merchant=merchant,
                category=c.category or "Other",
                amount_cents=amount,
                last_charged=last.posted_on,
                next_expected=_add_month(last.posted_on) if active else None,
                account=last.account.display_name if last.account else None,
                source="detected",
                active=active,
                charges=[(x.posted_on, -x.amount_cents) for x in s],
                note="; ".join(notes) or ("" if active else "not seen recently: cancelled?"),
            ))

    for mr in session.scalars(select(ManualRecurring)):
        nxt = None
        if mr.day_of_month:
            nxt = date(today.year, today.month, min(mr.day_of_month, 28))
            if nxt < today:
                nxt = _add_month(nxt)
        bills.append(RecurringBill(
            name=mr.name, merchant=mr.name, category=mr.category, amount_cents=mr.amount_cents,
            last_charged=None, next_expected=nxt, account=mr.paid_via, source="manual", note=mr.note or "",
        ))

    bills.sort(key=lambda b: (not b.active, -b.amount_cents))
    return bills


def monthly_total_cents(bills: list[RecurringBill]) -> int:
    return sum(b.amount_cents for b in bills if b.active)

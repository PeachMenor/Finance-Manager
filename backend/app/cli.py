"""Command-line tools. Run from backend/ with the virtual environment active:

    python -m app.cli demo                  load fake banks + fake Splitwise, print summary
    python -m app.cli plaid-sandbox-check   link a fake Plaid sandbox bank and sync it
                                            (needs PLAID_CLIENT_ID / PLAID_SECRET, PLAID_ENV=sandbox)
    python -m app.cli people-import FILE    load who-owes-whom balances from a JSON file
                                            (e.g. data/splitwise_balances.json, read off a screenshot)
    python -m app.cli summary               print net worth from your real database
    python -m app.cli accounts              list accounts with their ids
    python -m app.cli rename ID "NAME"      give an account your own name ("" to clear)
    python -m app.cli hide ID / unhide ID   leave an account off lists (still counted)
    python -m app.cli exclude ID / include ID  stop / resume counting an account in net worth
    python -m app.cli loan-set ...          add or update a loan entered by hand (see --help)
    python -m app.cli loans                 show hand-entered loans: estimated balance, payoff

`demo` and `plaid-sandbox-check` use data/demo.db, a separate database, so your
real data is never touched. `people-import` and `summary` use your real database.
"""

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_DB = REPO_ROOT / "data" / "demo.db"


def _point_at_demo_db() -> None:
    """Make the app use data/demo.db. Must run before ANY `app.*` import, because the
    database engine is created the first time `app.db.base` is imported (even
    indirectly, e.g. via `app.integrations.plaid`)."""
    os.environ["FM_DATABASE_PATH"] = str(DEMO_DB)


def _use_fresh_demo_db():
    """Wipe and recreate data/demo.db. Refuses to run against any other database."""
    from app.db.base import Base, engine, init_db

    # Safety guard: this drops every table, so never let it touch your real data.
    if Path(engine.url.database).resolve() != DEMO_DB.resolve():
        raise RuntimeError(f"Refusing to wipe {engine.url.database}: not the demo database.")
    Base.metadata.drop_all(engine)
    init_db(engine)


def _print_summary(session) -> None:
    from app.services.money import format_cents
    from app.services.networth import compute_net_worth

    s = compute_net_worth(session)
    width = 44
    print("\nACCOUNTS")
    hidden = [a for a in s.accounts if a.hidden and a.included]
    for a in (a for a in s.accounts if not a.hidden and a.included):
        sign = "−" if a.is_liability else " "
        note = ""
        label = f"{a.institution} · {a.name}"
        if len(label) > width:
            label = label[: width - 1] + "…"
        print(f"  {label:<{width}} {a.kind:<12} {sign}{format_cents(a.balance_cents):>12}{note}")
    if hidden:
        print(f"  ({len(hidden)} hidden account(s) not listed but still counted)")
    not_counted = [a for a in s.accounts if not a.included]
    if not_counted:
        print("\nSHOWN, NOT COUNTED IN NET WORTH")
        for a in not_counted:
            label = f"{a.institution} · {a.name}"
            if len(label) > width:
                label = label[: width - 1] + "…"
            print(f"  {label:<{width}} {a.kind:<12}  {format_cents(a.balance_cents):>12}")
    print("\nPEOPLE (who owes whom)")
    if not s.people:
        print("  (none)")
    for name, cents in s.people:
        text = f"owes you {format_cents(cents)}" if cents > 0 else f"you owe {format_cents(-cents)}"
        print(f"  {name:<{width}} {text}")
    print("\nTOTALS")
    print(f"  {'Assets':<{width}} {format_cents(s.assets_cents):>26}")
    print(f"  {'Liabilities':<{width}} {'−' + format_cents(s.liabilities_cents):>26}")
    print(f"  {'Owed to you':<{width}} {format_cents(s.owed_to_you_cents):>26}")
    print(f"  {'You owe':<{width}} {'−' + format_cents(s.you_owe_cents):>26}")
    print(f"  {'NET WORTH':<{width}} {format_cents(s.net_worth_cents):>26}")
    if s.excluded_cents:
        print(f"  {'Shown, not counted (total)':<{width}} {format_cents(s.excluded_cents):>26}")
    print()


def cmd_demo() -> int:
    _use_fresh_demo_db()
    from app.db.base import SessionLocal
    from app.db.models import DataSource
    from app.integrations.demo import (
        DEMO_PEOPLE,
        EXPECTED_NET_WORTH_CENTS,
        DemoBankIntegration,
    )
    from app.services.money import format_cents
    from app.services.networth import compute_net_worth
    from app.services.sync import sync_accounts, sync_person_balances

    with SessionLocal() as session:
        bank = DemoBankIntegration()
        first = sync_accounts(session, bank.source, bank.fetch_accounts())
        again = sync_accounts(session, bank.source, bank.fetch_accounts())  # must not duplicate
        sync_person_balances(session, DataSource.SPLITWISE, DEMO_PEOPLE)
        print(f"First sync: {first.accounts} accounts, {first.new_transactions} new transactions")
        print(f"Second sync: {again.new_transactions} new transactions (expected 0)")
        _print_summary(session)
        got = compute_net_worth(session).net_worth_cents
        ok = got == EXPECTED_NET_WORTH_CENTS
        print(f"Check: expected {format_cents(EXPECTED_NET_WORTH_CENTS)} → {'PASS' if ok else 'FAIL'}")
        return 0 if ok and again.new_transactions == 0 else 1


def cmd_plaid_sandbox_check() -> int:
    from app.config import get_settings  # noqa: F401  (loads .env)
    from app.integrations.plaid import PlaidClient

    client = PlaidClient.from_env()
    if client.env != "sandbox":
        print("Refusing: set PLAID_ENV=sandbox for this check.")
        return 1
    _use_fresh_demo_db()
    from app.db.base import SessionLocal
    from app.db.models import PlaidItem
    from app.services.sync import sync_plaid_items

    item_id, token = client.create_sandbox_access_token()
    with SessionLocal() as session:
        session.add(PlaidItem(item_id=item_id, access_token=token))
        session.commit()
        result = sync_plaid_items(session, client)
        print(f"Plaid sandbox: {result.accounts} accounts, {result.new_transactions} transactions")
        if result.new_transactions == 0:
            print("(Sandbox transactions can take a minute to appear; run again if needed.)")
        _print_summary(session)
    return 0


def cmd_people_import(path: str) -> int:
    """Replace who-owes-whom balances with the contents of a JSON file.

    File format (positive amount = they owe you, negative = you owe them):
        {"as_of": "2026-11-14",
         "people": [{"name": "Alex", "amount": 40.00}, {"name": "Sam", "amount": -25.50}]}
    Keep the file in data/ (git-ignored): it holds personal names and amounts.
    """
    import json

    from app.db.base import SessionLocal, init_db
    from app.db.models import DataSource
    from app.integrations.base import FetchedPersonBalance
    from app.services.money import to_cents
    from app.services.sync import sync_person_balances

    data = json.loads(Path(path).read_text())
    balances = [
        FetchedPersonBalance(
            external_id=p["name"].strip().lower(),
            name=p["name"].strip(),
            amount_cents=to_cents(str(p["amount"])),
            currency=p.get("currency", "USD"),
        )
        for p in data["people"]
    ]
    init_db()
    with SessionLocal() as session:
        kept = sync_person_balances(session, DataSource.SPLITWISE, balances)
        print(f"Imported {kept} balances (as of {data.get('as_of', 'unknown date')}).")
        _print_summary(session)
    return 0


def _rent_split(e: dict, rent_base_cents: int | None) -> str | None:
    """Split a rent expense's share into base rent and utilities, pro rata."""
    import json

    from app.services.money import to_cents

    cost, share = to_cents(str(e["cost"])), to_cents(str(e["your_share"]))
    if e["category"] != "Rent" or not rent_base_cents or cost <= rent_base_cents:
        return None
    rent_part = round(share * rent_base_cents / cost)
    return json.dumps({"Rent": rent_part, "Bills & utilities": share - rent_part})


def cmd_splitwise_import_expenses(path: str) -> int:
    """Replace stored shared expenses with the contents of a JSON file.

    {"rent_base": 1800.00,   # optional: fixed monthly rent; anything above it in a
                             # "Rent" expense is utilities billed with the rent
     "expenses": [{"date": "2026-11-01", "group": "Apartment", "description": "Rent",
                   "cost": 2000.00, "you_paid": 2000.00, "your_share": 1000.00,
                   "category": "Rent"}, ...]}
    With rent_base 1800, that rent is split pro rata: your 1000 share becomes
    900 Rent + 100 Bills & utilities. Keep the file in data/ (git-ignored).
    """
    import json
    from datetime import date

    from sqlalchemy import delete

    from app.db.base import SessionLocal, init_db
    from app.db.models import SplitExpense
    from app.services.money import format_cents, to_cents
    from app.services.spending import CATEGORIES, match_split_expenses

    data = json.loads(Path(path).read_text())
    rent_base = to_cents(str(data["rent_base"])) if data.get("rent_base") else None
    init_db()
    with SessionLocal() as session:
        session.execute(delete(SplitExpense))
        for e in data["expenses"]:
            if e["category"] not in CATEGORIES:
                print(f"Unknown category {e['category']!r} (use one of {CATEGORIES})")
                session.rollback()
                return 1
            session.add(SplitExpense(
                external_id=f"{e.get('group', '')}|{e['date']}|{e['description']}|{e['cost']}",
                spent_on=date.fromisoformat(e["date"]),
                group_name=e.get("group"),
                description=e["description"],
                cost_cents=to_cents(str(e["cost"])),
                you_paid_cents=to_cents(str(e["you_paid"])),
                share_cents=to_cents(str(e["your_share"])),
                category=e["category"],
                split_parts=_rent_split(e, rent_base),
            ))
        session.commit()
        print(f"Imported {len(data['expenses'])} shared expenses.")
        for m in match_split_expenses(session):
            e = m.expense
            if m.transaction is not None:
                how = f"matched your charge on {m.transaction.posted_on} ({m.transaction.description})"
            elif e.you_paid_cents:
                how = "NO matching charge found (paid from an unlinked account?)"
            else:
                how = "paid by someone else"
            parts = e.parts()
            split = (" = " + " + ".join(f"{format_cents(c)} {k}" for k, c in parts.items())) if len(parts) > 1 else ""
            print(f"  {e.spent_on} {e.description}: your share {format_cents(e.share_cents)}{split} "
                  f"of {format_cents(e.cost_cents)}; {how}")
    return 0


def cmd_nudge() -> int:
    """Print the weekly settle-up reminder (used by the scheduled phone nudge)."""
    from app.db.base import SessionLocal, init_db
    from app.services.nudge import build_nudge

    init_db()
    with SessionLocal() as session:
        print(build_nudge(session) or "Splitwise: all settled up.")
    return 0


def cmd_recurring() -> int:
    """List recurring monthly bills: detected from transactions plus ones added by hand."""
    from app.db.base import SessionLocal, init_db
    from app.services.money import format_cents
    from app.services.recurring import detect_recurring, monthly_total_cents

    init_db()
    with SessionLocal() as session:
        bills = detect_recurring(session, labels_path=REPO_ROOT / "data" / "recurring_labels.json")
        for b in bills:
            when = f"next ~{b.next_expected}" if b.next_expected else "—"
            extra = f"  ({b.note})" if b.note else ""
            print(f"  {b.name:<26} {format_cents(b.amount_cents):>10}/mo  {b.category:<18} "
                  f"{(b.account or ''):<30} {when}{extra}")
        print(f"\n  Monthly total (active): {format_cents(monthly_total_cents(bills))}")
    return 0


def cmd_recurring_add(a) -> int:
    """Add or update a monthly bill by hand (e.g. a share paid through Splitwise)."""
    from sqlalchemy import select

    from app.db.base import SessionLocal, init_db
    from app.db.models import ManualRecurring
    from app.services.money import to_cents
    from app.services.spending import CATEGORIES

    if a.category not in CATEGORIES:
        print(f"Category must be one of {CATEGORIES}")
        return 1
    init_db()
    with SessionLocal() as session:
        row = session.scalar(select(ManualRecurring).where(ManualRecurring.name == a.name))
        if row is None:
            row = ManualRecurring(name=a.name)
            session.add(row)
        row.amount_cents, row.category = to_cents(a.amount), a.category
        row.day_of_month, row.paid_via, row.note = a.day, a.paid_via, a.note
        session.commit()
        print(f"Saved monthly bill '{a.name}'.")
    return 0


def cmd_summary() -> int:
    from app.db.base import SessionLocal, init_db
    from app.services.loans import refresh_manual_loans

    init_db()
    with SessionLocal() as session:
        refresh_manual_loans(session)
        _print_summary(session)
    return 0


def cmd_accounts() -> int:
    from sqlalchemy import select

    from app.db.base import SessionLocal, init_db
    from app.db.models import Account

    init_db()
    with SessionLocal() as session:
        for a in session.scalars(select(Account).order_by(Account.id)):
            inst = a.institution.name if a.institution else "-"
            flag = ("  (hidden)" if a.hidden else "") + ("" if a.include_in_net_worth else "  (not counted)")
            print(f"  {a.id:>3}  {inst:<20} {a.display_name:<36} {a.kind.value}{flag}")
    return 0


def cmd_rename(account_id: int, nickname: str) -> int:
    from app.db.base import SessionLocal, init_db
    from app.db.models import Account

    init_db()
    with SessionLocal() as session:
        acct = session.get(Account, account_id)
        if acct is None:
            print(f"No account with id {account_id}. Run `python -m app.cli accounts`.")
            return 1
        acct.nickname = nickname.strip() or None
        session.commit()
        print(f"Account {account_id} is now shown as: {acct.display_name}")
    return 0


def cmd_set_counted(account_id: int, counted: bool) -> int:
    """Choose whether an account counts toward net worth (e.g. unvested stock awards don't)."""
    from app.db.base import SessionLocal, init_db
    from app.db.models import Account

    init_db()
    with SessionLocal() as session:
        acct = session.get(Account, account_id)
        if acct is None:
            print(f"No account with id {account_id}. Run `python -m app.cli accounts`.")
            return 1
        acct.include_in_net_worth = counted
        session.commit()
        state = "counted in net worth" if counted else "NOT counted in net worth (shown separately)"
        print(f"{acct.display_name} is now {state}.")
    return 0


def cmd_set_hidden(account_id: int, hidden: bool) -> int:
    from app.db.base import SessionLocal, init_db
    from app.db.models import Account

    init_db()
    with SessionLocal() as session:
        acct = session.get(Account, account_id)
        if acct is None:
            print(f"No account with id {account_id}. Run `python -m app.cli accounts`.")
            return 1
        acct.hidden = hidden
        session.commit()
        state = "hidden (still counted in net worth)" if hidden else "shown"
        print(f"{acct.display_name} is now {state}.")
    return 0


def cmd_loan_set(a) -> int:
    """Create or update a hand-entered loan from statement figures."""
    import re
    from datetime import date

    from sqlalchemy import select

    from app.db.base import SessionLocal, init_db
    from app.db.models import Account, AccountKind, BalanceSnapshot, DataSource, Institution, LoanTerms
    from app.services.loans import refresh_manual_loans
    from app.services.money import to_cents

    if not 1 <= a.day <= 28:
        print("--day must be 1-28 (use 28 for payments due on the 29th-31st).")
        return 1
    init_db()
    external_id = "loan-" + re.sub(r"[^a-z0-9]+", "-", a.name.lower()).strip("-")
    with SessionLocal() as session:
        inst = session.scalar(select(Institution).where(Institution.name == a.institution))
        if inst is None:
            inst = Institution(name=a.institution)
            session.add(inst)
        acct = session.scalar(
            select(Account).where(Account.source == DataSource.MANUAL, Account.external_id == external_id)
        )
        if acct is None:
            acct = Account(source=DataSource.MANUAL, external_id=external_id, kind=AccountKind.LOAN)
            session.add(acct)
        acct.name, acct.institution, acct.kind = a.name, inst, AccountKind.LOAN
        acct.balance_cents = to_cents(a.balance)
        session.flush()
        # Record it in the balance history so the net worth chart includes the loan.
        session.add(BalanceSnapshot(account_id=acct.id, balance_cents=acct.balance_cents))
        terms = session.scalar(select(LoanTerms).where(LoanTerms.account_id == acct.id))
        if terms is None:
            terms = LoanTerms(account_id=acct.id)
            session.add(terms)
        terms.principal_cents = to_cents(a.balance)
        terms.balance_as_of = date.fromisoformat(a.as_of)
        terms.apr_bps = to_cents(a.apr)  # 5.49 -> 549 (same x100 conversion as cents)
        terms.monthly_payment_cents = to_cents(a.payment)
        terms.payment_day = a.day
        terms.maturity_date = date.fromisoformat(a.maturity) if a.maturity else None
        terms.payment_match = a.payment_match or None
        terms.posting_lag_days = a.posting_lag
        terms.unpaid_interest_cents = to_cents(a.unpaid_interest) if a.unpaid_interest else None
        session.commit()
        refresh_manual_loans(session)
        print(f"Saved loan '{acct.display_name}' (account id {acct.id}).")
    return cmd_loans()


def cmd_loans() -> int:
    from datetime import date

    from sqlalchemy import select

    from app.db.base import SessionLocal, init_db
    from app.db.models import LoanTerms
    from app.services.loans import estimate_balance, months_to_payoff, refresh_manual_loans
    from app.services.money import format_cents

    init_db()
    with SessionLocal() as session:
        refresh_manual_loans(session)
        rows = session.scalars(select(LoanTerms)).all()
        if not rows:
            print("No hand-entered loans yet.")
        for t in rows:
            est = estimate_balance(t, date.today(), session)
            left = months_to_payoff(t, est.balance_cents)
            print(f"\n  {t.account.display_name}")
            print(f"    statement balance  {format_cents(t.principal_cents)} on {t.balance_as_of}"
                  + (f" (+ {format_cents(t.unpaid_interest_cents)} unpaid interest)" if t.unpaid_interest_cents else ""))
            if t.payment_match:
                print(f"    tracking payments  matching \"{t.payment_match}\" in bank transactions"
                      f" (posting lag {t.posting_lag_days or 0} day(s)), daily interest")
                for p in est.payments:
                    print(f"      paid {format_cents(p.amount_cents)} credited {p.effective_on}")
            print(f"    APR {t.apr_bps / 100:.2f}%, payment {format_cents(t.monthly_payment_cents)} on day {t.payment_day}")
            print(f"    estimated today    {format_cents(est.balance_cents)} "
                  f"({est.payments_applied} payment(s) applied, {format_cents(est.interest_paid_cents)} of it interest)")
            print(f"    payments left      {left if left is not None else 'payment does not cover interest!'}"
                  + (f" (maturity {t.maturity_date})" if t.maturity_date else ""))
    return 0


def cmd_resync_history() -> int:
    """Re-download all available transaction history (e.g. to fill in new fields).

    Resets each login's sync position; existing rows are updated, never duplicated,
    and your own categories are kept.
    """
    from sqlalchemy import select

    from app.config import get_settings  # noqa: F401  (loads .env)
    from app.db.base import SessionLocal, init_db
    from app.db.models import PlaidItem
    from app.integrations.plaid import PlaidClient
    from app.services.autosync import sync_everything

    init_db()
    client = PlaidClient.from_env()
    with SessionLocal() as session:
        for item in session.scalars(select(PlaidItem)):
            item.cursor = None
        session.commit()
        for r in sync_everything(session, client):
            print(f"  {r.institution}: {'ok' if r.ok else r.error}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="load fake data and print the summary")
    sub.add_parser("plaid-sandbox-check", help="sync a fake Plaid sandbox bank")
    imp = sub.add_parser("people-import", help="load who-owes-whom balances from JSON")
    imp.add_argument("file")
    sub.add_parser("summary", help="print net worth from your real database")
    sub.add_parser("nudge", help="print the weekly Splitwise settle-up reminder")
    sub.add_parser("recurring", help="list recurring monthly bills and subscriptions")
    ra = sub.add_parser("recurring-add", help="add a monthly bill by hand")
    ra.add_argument("--name", required=True)
    ra.add_argument("--amount", required=True, help="per month, your share")
    ra.add_argument("--category", required=True)
    ra.add_argument("--day", type=int, help="usual day of month")
    ra.add_argument("--paid-via", help='e.g. "Splitwise"')
    ra.add_argument("--note")
    sx = sub.add_parser("splitwise-import-expenses", help="load shared expenses (your share) from JSON")
    sx.add_argument("file")
    sub.add_parser("accounts", help="list accounts with their ids")
    ren = sub.add_parser("rename", help="give an account your own name")
    ren.add_argument("account_id", type=int)
    ren.add_argument("nickname")
    ls = sub.add_parser("loan-set", help="add or update a loan entered by hand")
    ls.add_argument("--name", required=True, help='e.g. "Car loan"')
    ls.add_argument("--institution", required=True, help='lender, e.g. "Example Auto Finance"')
    ls.add_argument("--balance", required=True, help="principal owed on the statement date, e.g. 15000.00")
    ls.add_argument("--as-of", required=True, help="statement date, YYYY-MM-DD")
    ls.add_argument("--apr", required=True, help="annual rate in percent, e.g. 5.49")
    ls.add_argument("--payment", required=True, help="monthly payment, e.g. 450.00")
    ls.add_argument("--day", required=True, type=int, help="day of month the payment posts (1-28)")
    ls.add_argument("--maturity", help="final payment date, YYYY-MM-DD (optional)")
    ls.add_argument("--payment-match", help='text in bank transactions for payments to this lender, '
                    'e.g. "Example Auto Finance"; enables payment tracking with daily interest')
    ls.add_argument("--posting-lag", type=int, default=0,
                    help="days between the lender crediting a payment and your bank posting it (default 0)")
    ls.add_argument("--unpaid-interest", help="interest accrued but not yet paid on the statement date "
                    "(e.g. after a principal-only payment), e.g. 12.34")
    sub.add_parser("loans", help="show hand-entered loans")
    sub.add_parser("resync-history", help="re-download all transaction history from Plaid")
    for cmd, text in (("exclude", "stop counting an account in net worth"),
                      ("include", "count an account in net worth again")):
        sp = sub.add_parser(cmd, help=text)
        sp.add_argument("account_id", type=int)
    for cmd in ("hide", "unhide"):
        sp = sub.add_parser(cmd, help=f"{cmd} an account on the dashboard")
        sp.add_argument("account_id", type=int)
    args = parser.parse_args(argv)

    # Choose the database before anything imports app.db (see _point_at_demo_db).
    if args.command in ("demo", "plaid-sandbox-check"):
        _point_at_demo_db()

    if args.command == "demo":
        return cmd_demo()
    if args.command == "plaid-sandbox-check":
        return cmd_plaid_sandbox_check()
    if args.command == "recurring":
        return cmd_recurring()
    if args.command == "recurring-add":
        return cmd_recurring_add(args)
    if args.command == "nudge":
        return cmd_nudge()
    if args.command == "splitwise-import-expenses":
        return cmd_splitwise_import_expenses(args.file)
    if args.command == "people-import":
        return cmd_people_import(args.file)
    if args.command == "accounts":
        return cmd_accounts()
    if args.command == "loan-set":
        return cmd_loan_set(args)
    if args.command == "loans":
        return cmd_loans()
    if args.command == "resync-history":
        return cmd_resync_history()
    if args.command in ("exclude", "include"):
        return cmd_set_counted(args.account_id, args.command == "include")
    if args.command in ("hide", "unhide"):
        return cmd_set_hidden(args.account_id, args.command == "hide")
    if args.command == "rename":
        return cmd_rename(args.account_id, args.nickname)
    return cmd_summary()


if __name__ == "__main__":
    sys.exit(main())

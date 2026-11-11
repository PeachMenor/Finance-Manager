"""Command-line tools. Run from backend/ with the virtual environment active:

    python -m app.cli demo                  load fake banks + fake Splitwise, print summary
    python -m app.cli plaid-sandbox-check   link a fake Plaid sandbox bank and sync it
                                            (needs PLAID_CLIENT_ID / PLAID_SECRET, PLAID_ENV=sandbox)
    python -m app.cli people-import FILE    load who-owes-whom balances from a JSON file
                                            (e.g. data/splitwise_balances.json, read off a screenshot)
    python -m app.cli summary               print net worth from your real database
    python -m app.cli accounts              list accounts with their ids
    python -m app.cli rename ID "NAME"      give an account your own name ("" to clear)

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
    for a in s.accounts:
        sign = "−" if a.is_liability else " "
        note = "" if a.included else "  (not counted)"
        label = f"{a.institution} · {a.name}"
        if len(label) > width:
            label = label[: width - 1] + "…"
        print(f"  {label:<{width}} {a.kind:<12} {sign}{format_cents(a.balance_cents):>12}{note}")
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
    print(f"  {'NET WORTH':<{width}} {format_cents(s.net_worth_cents):>26}\n")


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


def cmd_summary() -> int:
    from app.db.base import SessionLocal, init_db

    init_db()
    with SessionLocal() as session:
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
            print(f"  {a.id:>3}  {inst:<20} {a.display_name:<36} {a.kind.value}")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="load fake data and print the summary")
    sub.add_parser("plaid-sandbox-check", help="sync a fake Plaid sandbox bank")
    imp = sub.add_parser("people-import", help="load who-owes-whom balances from JSON")
    imp.add_argument("file")
    sub.add_parser("summary", help="print net worth from your real database")
    sub.add_parser("accounts", help="list accounts with their ids")
    ren = sub.add_parser("rename", help="give an account your own name")
    ren.add_argument("account_id", type=int)
    ren.add_argument("nickname")
    args = parser.parse_args(argv)

    # Choose the database before anything imports app.db (see _point_at_demo_db).
    if args.command in ("demo", "plaid-sandbox-check"):
        _point_at_demo_db()

    if args.command == "demo":
        return cmd_demo()
    if args.command == "plaid-sandbox-check":
        return cmd_plaid_sandbox_check()
    if args.command == "people-import":
        return cmd_people_import(args.file)
    if args.command == "accounts":
        return cmd_accounts()
    if args.command == "rename":
        return cmd_rename(args.account_id, args.nickname)
    return cmd_summary()


if __name__ == "__main__":
    sys.exit(main())

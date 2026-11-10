"""Command-line tools. Run from backend/ with the virtual environment active:

    python -m app.cli demo                  load fake banks + fake Splitwise, print summary
    python -m app.cli plaid-sandbox-check   link a fake Plaid sandbox bank and sync it
                                            (needs PLAID_CLIENT_ID / PLAID_SECRET, PLAID_ENV=sandbox)

Both write to data/demo.db, a separate database, so your real data is never touched.
"""

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_DB = REPO_ROOT / "data" / "demo.db"


def _use_fresh_demo_db():
    """Point the app at data/demo.db and wipe it. Must run before importing app.db."""
    os.environ["FM_DATABASE_PATH"] = str(DEMO_DB)
    from app.db.base import Base, engine, init_db

    Base.metadata.drop_all(engine)
    init_db(engine)


def _print_summary(session) -> None:
    from app.services.money import format_cents
    from app.services.networth import compute_net_worth

    s = compute_net_worth(session)
    width = 38
    print("\nACCOUNTS")
    for a in s.accounts:
        sign = "−" if a.is_liability else " "
        note = "" if a.included else "  (not counted)"
        label = f"{a.institution} · {a.name}"
        print(f"  {label:<{width}} {a.kind:<12} {sign}{format_cents(a.balance_cents):>12}{note}")
    print("\nPEOPLE (Splitwise)")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="load fake data and print the summary")
    sub.add_parser("plaid-sandbox-check", help="sync a fake Plaid sandbox bank")
    args = parser.parse_args(argv)
    if args.command == "demo":
        return cmd_demo()
    return cmd_plaid_sandbox_check()


if __name__ == "__main__":
    sys.exit(main())

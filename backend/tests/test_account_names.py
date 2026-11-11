import sqlite3

import pytest
from sqlalchemy import create_engine, inspect, select

from app import cli
from app.db.base import init_db
from app.db.models import Account, AccountKind, DataSource
from app.integrations.base import FetchedAccount
from app.integrations.plaid import account_display_name
from app.services.sync import sync_accounts


@pytest.mark.parametrize(
    "raw, expected",
    [
        ({"name": "CREDIT CARD", "official_name": "Rewards Visa"}, "Rewards Visa"),
        ({"name": "EVERYDAY CHECKING", "official_name": None}, "Everyday Checking"),
        ({"name": "Plaid Checking"}, "Plaid Checking"),
        ({}, "Account"),
    ],
)
def test_account_display_name(raw, expected):
    assert account_display_name(raw) == expected


def _card(mask="1234", name="Points Card®"):
    return [FetchedAccount("c1", "Test Bank", name, AccountKind.CREDIT_CARD, 100, mask=mask)]


def test_mask_shown_and_nickname_survives_sync(session):
    sync_accounts(session, DataSource.PLAID, _card())
    acct = session.scalar(select(Account))
    assert acct.display_name == "Points Card® ••1234"

    acct.nickname = "Travel Card"
    session.commit()
    sync_accounts(session, DataSource.PLAID, _card(name="Points Card® (renamed by bank)"))
    session.refresh(acct)
    assert acct.display_name == "Travel Card ••1234"  # sync never touches nickname


def test_rename_command(session, capsys):
    sync_accounts(session, DataSource.PLAID, _card())
    acct_id = session.scalar(select(Account)).id
    assert cli.cmd_rename(acct_id, "Travel Card") == 0
    assert "Travel Card ••1234" in capsys.readouterr().out
    assert cli.cmd_rename(acct_id, "  ") == 0  # blank clears the nickname
    session.expire_all()
    assert session.get(Account, acct_id).nickname is None
    assert cli.cmd_rename(9999, "x") == 1


def test_existing_database_gets_new_columns(tmp_path):
    # An "old" database created before nickname/mask existed, with data in it.
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE accounts (id INTEGER PRIMARY KEY, institution_id INTEGER, name VARCHAR(120),"
        " kind VARCHAR(11), source VARCHAR(9), external_id VARCHAR(200), currency VARCHAR(3),"
        " balance_cents INTEGER, balance_updated_at DATETIME, include_in_net_worth BOOLEAN)"
    )
    con.execute("INSERT INTO accounts (name, kind, source, external_id, currency, balance_cents,"
                " include_in_net_worth) VALUES ('Old', 'CHECKING', 'PLAID', 'x', 'USD', 5, 1)")
    con.commit()
    con.close()

    engine = create_engine(f"sqlite:///{path}")
    init_db(engine)
    init_db(engine)  # running twice is harmless
    cols = {c["name"] for c in inspect(engine).get_columns("accounts")}
    assert {"nickname", "mask"} <= cols
    with engine.connect() as c:
        assert c.exec_driver_sql("SELECT name, balance_cents FROM accounts").one() == ("Old", 5)

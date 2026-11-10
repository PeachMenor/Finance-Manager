import json

import pytest

from app import cli
from app.services.networth import compute_net_worth


def test_people_import_replaces_balances(session, tmp_path, capsys):
    f = tmp_path / "balances.json"
    f.write_text(json.dumps({
        "as_of": "2026-11-13",
        "people": [
            {"name": "Alex", "amount": 40.00},
            {"name": " Sam ", "amount": -25.5},
            {"name": "Kim", "amount": 0},
        ],
    }))
    assert cli.cmd_people_import(str(f)) == 0
    s = compute_net_worth(session)
    assert s.people == [("Alex", 4000), ("Sam", -2550)]  # trimmed, zero dropped
    assert "Imported 2 balances (as of 2026-11-13)" in capsys.readouterr().out

    # Next week's screenshot: Alex paid back, so only Sam remains.
    f.write_text(json.dumps({"people": [{"name": "Sam", "amount": -10}]}))
    cli.cmd_people_import(str(f))
    session.expire_all()
    assert compute_net_worth(session).people == [("Sam", -1000)]


def test_demo_wipe_refuses_non_demo_database(session):
    # Tests run against a temp database, which is not data/demo.db.
    with pytest.raises(RuntimeError, match="Refusing to wipe"):
        cli._use_fresh_demo_db()

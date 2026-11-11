from datetime import datetime, timedelta, timezone

from app.db.models import DataSource
from app.integrations.base import FetchedPersonBalance
from app.services.nudge import MAX_CHARS, build_nudge
from app.services.sync import sync_person_balances


def _people(session, rows):
    sync_person_balances(session, DataSource.SPLITWISE,
                         [FetchedPersonBalance(f"p{i}", n, c) for i, (n, c) in enumerate(rows)])


def test_nudge_lists_biggest_first(session):
    _people(session, [("Sam Lee", -12_345), ("Alex Kim", -500), ("Jo Park", 40_000), ("Kim", 0)])
    text = build_nudge(session)
    assert text == "Splitwise: Pay $128: Sam $123, Alex $5. Collect $400: Jo $400."


def test_nudge_fits_a_phone_notification(session):
    many = [(f"Person{i} Surname", -(i + 1) * 1_000) for i in range(30)] + \
           [(f"Friend{i} Name", (i + 1) * 2_000) for i in range(30)]
    _people(session, many)
    text = build_nudge(session)
    assert len(text) <= MAX_CHARS and "+27 more" in text


def test_nudge_warns_when_balances_are_old(session):
    _people(session, [("Sam", -1_000)])
    later = datetime.now(timezone.utc) + timedelta(days=9)
    assert "send a new Splitwise screenshot" in build_nudge(session, now=later)
    assert "screenshot" not in build_nudge(session)


def test_nothing_to_settle(session):
    assert build_nudge(session) is None


def test_pay_one_person_at_a_time(session):
    from app.services.nudge import build_pay_one

    _people(session, [("Sam Lee", -12_345), ("Alex Kim", -500), ("Jo Park", 40_000)])
    assert build_pay_one(session) == "This week, pay Sam $123 on Splitwise. 1 more after that ($5). Ask Jo for $400."
    _people(session, [("Alex Kim", -500)])  # next week's screenshot: Sam paid, nobody owes you
    assert build_pay_one(session) == "This week, pay Alex $5 on Splitwise."
    _people(session, [])
    assert build_pay_one(session) is None


def test_settle_after_confirmation(session, tmp_path, monkeypatch, capsys):
    import json

    from sqlalchemy import select

    from app import cli
    from app.db.models import PersonBalance
    from app.services.nudge import next_payee

    monkeypatch.setenv("FM_DATA_DIR", str(tmp_path))
    (tmp_path / "splitwise_balances.json").write_text(json.dumps({"people": [
        {"name": "Sam Lee", "amount": -123.45}, {"name": "Alex Kim", "amount": -5.00}, {"name": "Jo Park", "amount": 400.0}]}))
    _people(session, [("Sam Lee", -12_345), ("Alex Kim", -500), ("Jo Park", 40_000)])
    assert next_payee(session) == ("Sam Lee", 12_345)

    assert cli.main(["people-settle", "Jo"]) == 1  # Jo owes you; you can't "pay" them
    assert cli.main(["people-settle", "Sam", "--amount", "100"]) == 0  # partial
    session.expire_all()
    assert session.scalar(select(PersonBalance).where(PersonBalance.name == "Sam Lee")).amount_cents == -2_345
    assert cli.main(["people-settle", "Sam Lee"]) == 0  # the rest
    session.expire_all()
    assert next_payee(session) == ("Alex Kim", 500)
    left = json.loads((tmp_path / "splitwise_balances.json").read_text())["people"]
    assert [p["name"] for p in left] == ["Alex Kim", "Jo Park"]
    log = json.loads((tmp_path / "settlements.json").read_text())
    assert [(x["name"], x["paid"]) for x in log] == [("Sam Lee", 100.0), ("Sam Lee", 23.45)]
    assert "all settled with them" in capsys.readouterr().out


def test_sms_reminder_and_settle_pending(session, tmp_path, monkeypatch, capsys):
    import json

    from app import cli

    monkeypatch.setenv("FM_DATA_DIR", str(tmp_path))
    _people(session, [("Sam Lee", -12_345), ("Jo Park", 40_000)])
    assert cli.main(["nudge", "--sms"]) == 0
    out = capsys.readouterr().out
    assert "pay Sam Lee $123.45 on Splitwise this week." in out
    assert "add confirm_page" in out  # no confirm page configured in this test
    assert json.loads((tmp_path / "pending_settle.json").read_text())["name"] == "Sam Lee"
    assert cli.main(["people-settle", "--pending"]) == 0
    assert not (tmp_path / "pending_settle.json").exists()
    assert cli.main(["people-settle", "--pending"]) == 1  # nothing left to confirm
    _people(session, [("Jo Park", 40_000)])
    assert cli.main(["nudge", "--sms"]) == 0
    assert "don't owe anyone" in capsys.readouterr().out


def test_confirm_link():
    from app.cli import sms_with_confirm_link

    page = "https://claude.ai/artifact/EXAMPLE"
    text = sms_with_confirm_link("Finance: pay Sam $5.", page)
    assert "mailto:" not in text
    assert f"{page}#paid" in text  # one tap records PAID
    assert text.splitlines()[-1].endswith(page)  # plain link for a partial amount
    assert "No confirm page set" in sms_with_confirm_link("x", None)

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

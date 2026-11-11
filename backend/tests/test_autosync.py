"""Automatic sync, run against the fake Plaid server (never the real one)."""

import asyncio

from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import PlaidItem, Transaction
from app.services import autosync
from app.services.autosync import AutoSyncState, auto_sync_hours, auto_sync_loop, run_once
from tests.fake_plaid import FakePlaid


def _link(session):
    session.add(PlaidItem(item_id="item-1", access_token="tok-1"))
    session.commit()


def test_run_once_syncs_and_records_status(session):
    _link(session)
    state = AutoSyncState()
    run_once(SessionLocal, FakePlaid().client, state)
    assert state.last_ok is True
    assert state.last_message == "1 logins, 3 new transactions"
    assert len(session.scalars(select(Transaction)).all()) == 3


def test_run_once_reports_login_problems_without_raising(session):
    _link(session)
    state = AutoSyncState()
    broken = FakePlaid(fail={"/accounts/balance/get": "ITEM_LOGIN_REQUIRED"})
    run_once(SessionLocal, broken.client, state)
    assert state.last_ok is False and "ITEM_LOGIN_REQUIRED" in state.last_message


def test_run_once_survives_unexpected_errors(session):
    def no_network():
        raise ConnectionError("offline")

    state = AutoSyncState()
    run_once(SessionLocal, no_network, state)
    assert state.last_ok is False and state.last_message == "failed: ConnectionError"


def test_loop_syncs_at_start_and_stops_cleanly(session):
    _link(session)
    state = AutoSyncState()

    async def scenario():
        task = asyncio.create_task(
            auto_sync_loop(SessionLocal, FakePlaid().client, hours=6, first_delay=0, state=state)
        )
        for _ in range(100):  # wait for the first run (it happens in a worker thread)
            if state.last_finished_at:
                break
            await asyncio.sleep(0.02)
        assert state.running is True
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert state.last_ok is True and state.running is False


def test_hours_setting(monkeypatch):
    monkeypatch.setenv("FM_AUTO_SYNC_HOURS", "12")
    assert auto_sync_hours() == 12
    monkeypatch.setenv("FM_AUTO_SYNC_HOURS", "0")
    assert auto_sync_hours() == 0
    monkeypatch.setenv("FM_AUTO_SYNC_HOURS", "lots")
    assert auto_sync_hours() == autosync.DEFAULT_HOURS
    monkeypatch.delenv("FM_AUTO_SYNC_HOURS")
    assert auto_sync_hours() == 6

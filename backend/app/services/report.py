"""Numbers for the monthly report (the PDF itself is drawn in report_pdf.py).

For a month it gathers:
- income, expenses (by category) and savings, using the same spending
  calculation as the dashboard
- net worth and chosen account values at the END of the month (from the
  balance history every sync records; the latest balance on or before that day)
- the same figures for the previous month, and season totals (Winter = Dec-Feb,
  Spring = Mar-May, Summer = Jun-Aug, Fall = Sep-Nov) against the previous season
- budget status at the end of the month

Which accounts appear is set in a private file (data/report.json):
    {"holdings": [{"name": "Brokerage", "account_ids": [3, 4]}, ...]}
Nothing before the tracking start date is used.
"""

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Account, BalanceSnapshot, PersonBalance
from app.services.budgets import BudgetConfig, budget_progress
from app.services.spending import CATEGORIES, RentRule, collect_spending

SEASONS = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring", 5: "Spring",
           6: "Summer", 7: "Summer", 8: "Summer", 9: "Fall", 10: "Fall", 11: "Fall"}


def month_bounds(key: str) -> tuple[date, date]:
    y, m = int(key[:4]), int(key[5:])
    first = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return first, nxt - timedelta(days=1)


def prev_month(key: str) -> str:
    y, m = int(key[:4]), int(key[5:])
    return f"{y - (m == 1):04d}-{(m - 2) % 12 + 1:02d}"


def season_months(key: str) -> list[str]:
    """The three months of the season `key` falls in (Winter spans the new year)."""
    y, m = int(key[:4]), int(key[5:])
    start_month = {12: 12, 1: 12, 2: 12}.get(m, ((m - 3) // 3) * 3 + 3)
    start_year = y - 1 if m in (1, 2) else y
    out, yy, mm = [], start_year, start_month
    for _ in range(3):
        out.append(f"{yy:04d}-{mm:02d}")
        yy, mm = (yy + 1, 1) if mm == 12 else (yy, mm + 1)
    return out


def balance_at(session: Session, account_ids: list[int], day: date) -> int | None:
    """Sum of each account's last recorded balance on or before `day` (None if no history)."""
    end = datetime.combine(day, time.max).replace(tzinfo=timezone.utc)
    total, found = 0, False
    for aid in account_ids:
        cents = session.scalar(
            select(BalanceSnapshot.balance_cents)
            .where(BalanceSnapshot.account_id == aid, BalanceSnapshot.taken_at <= end)
            .order_by(BalanceSnapshot.taken_at.desc()).limit(1))
        if cents is not None:
            total, found = total + cents, True
    return total if found else None


def net_worth_at(session: Session, day: date) -> int | None:
    """Net worth at the end of `day`, matching the dashboard's formula: account balances
    from history (counted accounts only) plus Splitwise balances. Splitwise has no
    history, so its latest balances are used (they're refreshed every week)."""
    accounts = session.scalars(select(Account).where(Account.include_in_net_worth.is_(True))).all()
    total, found = 0, False
    for a in accounts:
        v = balance_at(session, [a.id], day)
        if v is not None:
            total += -v if a.kind.is_liability else v
            found = True
    if not found:
        return None
    return total + sum(session.scalars(select(PersonBalance.amount_cents).where(PersonBalance.currency == "USD")))


def _flows(session: Session, start: date, end: date, rule: RentRule | None) -> dict:
    col = collect_spending(session, start, end, rule)
    by_cat: dict[str, int] = {}
    for it in col.spend:
        by_cat[it.category] = by_cat.get(it.category, 0) + it.cents
    income = sum(c for _, c, _ in col.income)
    expenses = sum(by_cat.values())
    return {"income_cents": income, "expenses_cents": expenses, "saved_cents": income - expenses,
            "savings_rate": round((income - expenses) / income, 4) if income > 0 else None,
            "by_category": {c: by_cat[c] for c in CATEGORIES if by_cat.get(c)}}


def build_month_report(session: Session, month: str, *, today: date | None = None,
                       tracking_start: date | None = None, rent_rule: RentRule | None = None,
                       budgets: BudgetConfig | None = None, holdings: list[dict] | None = None) -> dict:
    today = today or date.today()
    first, last = month_bounds(month)
    upto = min(last, today)
    start = max(first, tracking_start) if tracking_start else first

    def in_range(key: str) -> bool:
        return not tracking_start or month_bounds(key)[1] >= tracking_start

    this = _flows(session, start, upto, rent_rule)
    pm = prev_month(month)
    prev = None
    if in_range(pm):
        p_first, p_last = month_bounds(pm)
        prev = _flows(session, max(p_first, tracking_start) if tracking_start else p_first, p_last, rent_rule)

    pm_last = month_bounds(pm)[1]
    values = []
    for h in holdings or []:
        now_v = balance_at(session, h["account_ids"], upto)
        before_v = balance_at(session, h["account_ids"], pm_last) if in_range(pm) else None
        values.append({"name": h["name"], "end_cents": now_v, "prev_end_cents": before_v})
    nw_now = net_worth_at(session, upto)
    nw_prev = net_worth_at(session, pm_last) if in_range(pm) else None

    def season_totals(months: list[str]) -> dict | None:
        months = [k for k in months if in_range(k) and month_bounds(k)[0] <= upto]
        if not months:
            return None
        s_first = month_bounds(months[0])[0]
        if tracking_start:
            s_first = max(s_first, tracking_start)
        f = _flows(session, s_first, min(month_bounds(months[-1])[1], upto), rent_rule)
        f["months"] = months
        return f

    cur_season = season_months(month)
    prev_season = season_months(prev_month(cur_season[0]))
    season = {
        "name": f"{SEASONS[int(month[5:])]} {cur_season[0][:4]}" + (f"-{cur_season[-1][2:4]}" if cur_season[0][:4] != cur_season[-1][:4] else ""),
        "current": season_totals(cur_season),
        "previous_name": f"{SEASONS[int(prev_season[0][5:])]} {prev_season[0][:4]}",
        "previous": season_totals(prev_season),
    }

    budget = budget_progress(session, budgets, upto, rent_rule) if budgets else None
    return {
        "month": month, "from": start.isoformat(), "through": upto.isoformat(),
        "complete": upto == last, "generated": today.isoformat(),
        "this": this, "previous": prev, "previous_month": pm,
        "net_worth_end_cents": nw_now, "net_worth_prev_end_cents": nw_prev,
        "holdings": values, "season": season, "budgets": budget,
    }


def load_holdings(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text()).get("holdings", []) if Path(path).exists() else []

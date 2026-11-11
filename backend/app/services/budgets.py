"""Budgets: what you planned to spend per line, against what you've actually spent.

Budget lines live in a private, git-ignored file (data/budgets.json):

    {"year_start": "2026-01-01",
     "lines": [{"name": "Groceries", "category": "Food & groceries", "sub": "groceries", "monthly": 300},
               {"name": "Eating out", "category": "Food & groceries", "exclude_sub": "groceries", "monthly": 200},
               {"name": "Travel", "category": "Transport & travel", "annual": 3000}]}

A line picks spending by category, optionally narrowed to one finer sub-line
(`sub`) or everything except one (`exclude_sub`). Its limit is `monthly` (a cap
every calendar month) or `annual` (for the whole budget year).

Spending comes from the same calculation as the dashboard (only your share of
shared expenses, rent rule applied), counted from the start of the budget year.

Status:
- monthly lines: this month's spending vs the cap (the first, partial month of
  the budget year gets a pro-rated cap): over / near (80%+) / on track
- annual lines: spending adds up across the whole budget year and is flagged
  only against the yearly limit: over / near (80%+) / on track. No per-month
  pacing: these costs are lumpy (tuition, a doctor's bill, a trip).
"""

import calendar
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.services.money import to_cents
from app.services.spending import RentRule, canonical, collect_spending

NEAR = 0.8


@dataclass
class BudgetLine:
    name: str
    category: str
    sub: str | None = None
    exclude_sub: str | None = None
    monthly_cents: int | None = None
    annual_cents: int = 0

    def matches(self, category: str, sub: str | None) -> bool:
        if category != self.category:
            return False
        if self.sub is not None and sub != self.sub:
            return False
        return not (self.exclude_sub is not None and sub == self.exclude_sub)


@dataclass
class BudgetConfig:
    year_start: date
    lines: list[BudgetLine]

    @property
    def year_end(self) -> date:
        try:
            nxt = self.year_start.replace(year=self.year_start.year + 1)
        except ValueError:  # Feb 29
            nxt = self.year_start.replace(year=self.year_start.year + 1, day=28)
        return nxt - timedelta(days=1)

    @classmethod
    def load(cls, path: Path) -> "BudgetConfig | None":
        if not Path(path).exists():
            return None
        raw = json.loads(Path(path).read_text())
        lines = []
        for x in raw.get("lines", []):
            monthly = to_cents(str(x["monthly"])) if x.get("monthly") is not None else None
            annual = monthly * 12 if monthly is not None else to_cents(str(x.get("annual", 0)))
            lines.append(BudgetLine(x["name"], canonical(x["category"]), x.get("sub"), x.get("exclude_sub"),
                                    monthly, annual))
        return cls(date.fromisoformat(raw["year_start"]), lines)


def _status_monthly(spent: int, cap: int) -> str:
    if cap <= 0:
        return "on track"
    if spent > cap:
        return "over"
    return "near" if spent >= cap * NEAR else "on track"


def budget_progress(session: Session, cfg: BudgetConfig, today: date | None = None,
                    rent_rule: RentRule | None = None) -> dict:
    today = min(today or date.today(), cfg.year_end)
    days_in_year = (cfg.year_end - cfg.year_start).days + 1
    elapsed_days = max(0, (today - cfg.year_start).days + 1)
    fraction = elapsed_days / days_in_year
    col = collect_spending(session, cfg.year_start, today, rent_rule)

    month_start = max(today.replace(day=1), cfg.year_start)
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    # The budget year's first month is partial: pro-rate its monthly caps.
    month_share = 1.0 if month_start.day == 1 else (days_in_month - month_start.day + 1) / days_in_month

    lines = []
    for ln in cfg.lines:
        year_spent = sum(it.cents for it in col.spend if ln.matches(it.category, it.sub))
        month_spent = sum(it.cents for it in col.spend if it.day >= month_start and ln.matches(it.category, it.sub))
        expected = round(ln.annual_cents * fraction)
        row = {
            "name": ln.name, "category": ln.category,
            "annual_cents": ln.annual_cents, "year_spent_cents": year_spent,
            "year_left_cents": ln.annual_cents - year_spent,
            "expected_by_now_cents": expected,
        }
        if ln.monthly_cents is not None:
            cap = round(ln.monthly_cents * month_share)
            row.update({"period": "monthly", "monthly_cents": ln.monthly_cents, "month_cap_cents": cap,
                        "month_spent_cents": month_spent, "status": _status_monthly(month_spent, cap)})
        else:
            if year_spent > ln.annual_cents:
                status = "over"
            elif ln.annual_cents and year_spent >= ln.annual_cents * NEAR:
                status = "near"
            else:
                status = "on track"
            row.update({"period": "annual", "status": status})
        lines.append(row)

    return {
        "year_start": cfg.year_start.isoformat(), "year_end": cfg.year_end.isoformat(),
        "elapsed_fraction": round(fraction, 4), "month_start": month_start.isoformat(),
        "month_share": round(month_share, 4),
        "total_annual_cents": sum(ln.annual_cents for ln in cfg.lines),
        "total_spent_cents": sum(r["year_spent_cents"] for r in lines),
        "lines": lines,
    }

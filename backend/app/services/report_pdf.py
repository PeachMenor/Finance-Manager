"""Draw the monthly report as a PDF (ReportLab), in the dashboard's ledger style.

Every comparison is shown as a signed change, coloured green when it's good for
you (more income, less spending, more saved, higher balances) and red when it's
not, always with the number written out so it never relies on colour alone.
"""

from datetime import date
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Rect
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor("#16150f")
MUTED = colors.HexColor("#85817a")
RULE = colors.HexColor("#e2ded5")
ACCENT = colors.HexColor("#1f5f8b")
BAR = colors.HexColor("#cdc8bd")
GOOD = colors.HexColor("#1a7f37")
BAD = colors.HexColor("#c62828")
WARN = colors.HexColor("#b7791f")

H1 = ParagraphStyle("h1", fontName="Times-Bold", fontSize=22, leading=26, textColor=INK)
H2 = ParagraphStyle("h2", fontName="Times-Bold", fontSize=14, leading=18, textColor=INK, spaceBefore=14, spaceAfter=6)
BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK)
SMALL = ParagraphStyle("small", fontName="Helvetica", fontSize=8, leading=11, textColor=MUTED)
EYEBROW = ParagraphStyle("eye", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=MUTED)
RIGHT = ParagraphStyle("right", parent=BODY, alignment=TA_RIGHT)


def money(cents: int | None, sign: bool = False) -> str:
    if cents is None:
        return "—"
    s = f"${abs(cents) / 100:,.2f}"
    if cents < 0:
        return "−" + s
    return ("+" + s) if sign and cents > 0 else s


def pct(r: float | None) -> str:
    return "—" if r is None else f"{'−' if r < 0 else ''}{abs(r) * 100:.0f}%"


def month_name(key: str) -> str:
    return date(int(key[:4]), int(key[5:]), 1).strftime("%B %Y")


def _change(now: int | None, before: int | None, good_when_up: bool = True) -> Paragraph:
    if now is None or before is None:
        return Paragraph("—", RIGHT)
    diff = now - before
    rel = f" ({diff / abs(before) * 100:+.0f}%)" if before else ""
    color = MUTED if diff == 0 else (GOOD if (diff > 0) == good_when_up else BAD)
    return Paragraph(f'<font color="{color.hexval()}">{money(diff, sign=True)}{rel}</font>', RIGHT)


def _table(rows: list[list], widths: list[float], header: bool = True) -> Table:
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    style = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
    ]
    if header:
        style += [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED)]
    t.setStyle(TableStyle(style))
    return t


def _bar(value: int, max_value: int, width: float = 1.4 * inch) -> Drawing:
    d = Drawing(width, 8)
    d.add(Rect(0, 1, width, 6, fillColor=colors.HexColor("#efece6"), strokeColor=None, rx=3, ry=3))
    w = max(0.0, min(1.0, value / max_value if max_value else 0)) * width
    if w >= 1:  # tiny values: no fill (a sub-pixel rounded bar renders as a stray mark)
        r = min(3, w / 2)
        d.add(Rect(0, 1, w, 6, fillColor=ACCENT, strokeColor=None, rx=r, ry=r))
    return d


def _highlights(r: dict) -> list[str]:
    out = []
    t, p = r["this"], r["previous"]
    if t["by_category"]:
        top = max(t["by_category"].items(), key=lambda x: x[1])
        share = top[1] / t["expenses_cents"] * 100 if t["expenses_cents"] else 0
        out.append(f"Biggest spending category: <b>{top[0]}</b>, {money(top[1])} ({share:.0f}% of expenses).")
    if p:
        changes = [(c, t["by_category"].get(c, 0) - p["by_category"].get(c, 0))
                   for c in set(t["by_category"]) | set(p["by_category"])]
        up = max(changes, key=lambda x: x[1], default=None)
        down = min(changes, key=lambda x: x[1], default=None)
        if up and up[1] > 0:
            out.append(f"Largest increase vs last month: <b>{up[0]}</b> ({money(up[1], sign=True)}).")
        if down and down[1] < 0:
            out.append(f"Largest decrease vs last month: <b>{down[0]}</b> ({money(down[1])}).")
    if t["savings_rate"] is not None:
        out.append(f"You saved <b>{pct(t['savings_rate'])}</b> of your income ({money(t['saved_cents'])}).")
    if r["budgets"]:
        flagged = [ln for ln in r["budgets"]["lines"] if ln["status"] in ("near", "over")]
        for ln in flagged:
            out.append(f"Budget <b>{ln['name']}</b> is <b>{ln['status']}</b>.")
        if not flagged:
            out.append("All budgets are on track.")
    return out


def render_month_report(r: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=LETTER, leftMargin=0.8 * inch, rightMargin=0.8 * inch,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                            title=f"Monthly report {r['month']}", author="Finance Manager")
    W = LETTER[0] - 1.6 * inch
    story = []
    t, p = r["this"], r["previous"]
    fmt = lambda iso: date.fromisoformat(iso).strftime("%b %-d, %Y")  # noqa: E731

    story += [Paragraph("PERSONAL FINANCE · MONTHLY REPORT", EYEBROW), Spacer(1, 4),
              Paragraph(month_name(r["month"]), H1),
              Paragraph(f"{fmt(r['from'])} – {fmt(r['through'])}"
                        + ("" if r["complete"] else " · <b>month in progress</b>")
                        + f" · generated {fmt(r['generated'])}", SMALL), Spacer(1, 10)]

    prev_label = month_name(r["previous_month"]).split()[0][:3] if p else "Prev."
    section = [Paragraph("The month at a glance", H2)]
    rows = [["", "THIS MONTH", prev_label.upper(), "CHANGE"],
            ["Income", money(t["income_cents"]), money(p["income_cents"]) if p else "—",
             _change(t["income_cents"], p["income_cents"] if p else None)],
            ["Expenses", money(t["expenses_cents"]), money(p["expenses_cents"]) if p else "—",
             _change(t["expenses_cents"], p["expenses_cents"] if p else None, good_when_up=False)],
            ["Saved", f"{money(t['saved_cents'])} ({pct(t['savings_rate'])})",
             f"{money(p['saved_cents'])} ({pct(p['savings_rate'])})" if p else "—",
             _change(t["saved_cents"], p["saved_cents"] if p else None)],
            ["Net worth (month end)", money(r["net_worth_end_cents"]), money(r["net_worth_prev_end_cents"]),
             _change(r["net_worth_end_cents"], r["net_worth_prev_end_cents"])]]
    section.append(_table(rows, [W * 0.34, W * 0.24, W * 0.2, W * 0.22]))
    story.append(KeepTogether(section))

    if r["holdings"]:
        section = [Paragraph("Investments (value at month end)", H2)]
        rows = [["ACCOUNT", "THIS MONTH", prev_label.upper(), "CHANGE"]]
        for h in r["holdings"]:
            rows.append([Paragraph(h["name"], BODY), money(h["end_cents"]), money(h["prev_end_cents"]),
                         _change(h["end_cents"], h["prev_end_cents"])])
        section.append(_table(rows, [W * 0.4, W * 0.2, W * 0.18, W * 0.22]))
        section.append(Paragraph("Values move with the market; each is the last balance synced on or before the "
                                 "month's last day. Unvested RSUs and the 401(k) aren't counted in net worth.", SMALL))
        story.append(KeepTogether(section))

    if t["by_category"]:
        section = [Paragraph("Where the money went", H2)]
        biggest = max(t["by_category"].values())
        rows = [["CATEGORY", "", "THIS MONTH", prev_label.upper(), "CHANGE"]]
        cats = sorted(t["by_category"].items(), key=lambda x: -x[1])
        for cat, cents in cats:
            before = p["by_category"].get(cat, 0) if p else None
            rows.append([cat, _bar(max(cents, 0), biggest), money(cents), money(before) if p else "—",
                         _change(cents, before, good_when_up=False)])
        section.append(_table(rows, [W * 0.27, W * 0.22, W * 0.17, W * 0.15, W * 0.19]))
        story.append(KeepTogether(section))

    b = r["budgets"]
    if b:
        section = [Paragraph("Budgets", H2)]
        rows = [["BUDGET", "LIMIT", "SPENT", "STATUS"]]
        for ln in b["lines"]:
            if ln["period"] == "monthly":
                limit, spent = f"{money(ln['month_cap_cents'])} this month", money(ln["month_spent_cents"])
            else:
                limit, spent = f"{money(ln['annual_cents'])} this year", f"{money(ln['year_spent_cents'])} so far"
            color = {"over": BAD, "near": WARN}.get(ln["status"], MUTED)
            rows.append([ln["name"], limit, spent,
                         Paragraph(f'<font color="{color.hexval()}">{ln["status"]}</font>', RIGHT)])
        section.append(_table(rows, [W * 0.32, W * 0.28, W * 0.2, W * 0.2]))
        note = ("Monthly budgets are flagged at 80% of the month's cap; yearly budgets at 80% of the yearly limit. "
                f"Budget year: {fmt(b['year_start'])} – {fmt(b['year_end'])}.")
        if b["month_share"] < 1:
            note += (f" This month's budget counts spending from {fmt(b['month_start'])} only (the budget year's "
                     f"first, partial month), so caps are pro-rated to {b['month_share'] * 100:.0f}%.")
        section.append(Paragraph(note, SMALL))
        story.append(KeepTogether(section))

    s = r["season"]
    story.append(Paragraph(f"Season: {s['name']} so far vs {s['previous_name']}", H2))
    cur, prv = s["current"], s["previous"]
    if cur and prv:
        rows = [["", s["name"].upper(), s["previous_name"].upper(), "CHANGE"],
                ["Income", money(cur["income_cents"]), money(prv["income_cents"]),
                 _change(cur["income_cents"], prv["income_cents"])],
                ["Expenses", money(cur["expenses_cents"]), money(prv["expenses_cents"]),
                 _change(cur["expenses_cents"], prv["expenses_cents"], good_when_up=False)],
                ["Saved", money(cur["saved_cents"]), money(prv["saved_cents"]),
                 _change(cur["saved_cents"], prv["saved_cents"])]]
        story.append(_table(rows, [W * 0.3, W * 0.24, W * 0.24, W * 0.22]))
    else:
        story.append(Paragraph("Not enough history yet: season comparisons start once a full previous season "
                               "has been tracked.", BODY))

    hl = _highlights(r)
    if hl:
        story.append(Paragraph("Highlights", H2))
        for line in hl:
            story.append(Paragraph(f"• {line}", BODY))

    story += [Spacer(1, 14), Paragraph(
        "Spending counts only your share of shared expenses; rent is your fixed monthly share. Card payments, "
        "loan payments, transfers and investing are not spending. Employer reimbursements reduce the expense "
        "they repay.", SMALL)]
    doc.build(story)
    return path

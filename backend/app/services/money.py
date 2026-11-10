"""Convert between dollar amounts and the integer cents stored in the database."""

from decimal import ROUND_HALF_UP, Decimal


def to_cents(amount: str | int | float | Decimal) -> int:
    """Turn a dollar amount like "1,234.56" or 12.3 into cents (123456, 1230).

    Goes through Decimal (from str) so 0.1 + 0.2 style float errors can't creep in.
    Rounds half-up to the nearest cent.
    """
    if isinstance(amount, str):
        amount = amount.replace(",", "").replace("$", "").strip()
    value = Decimal(str(amount))
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_cents(cents: int, currency_symbol: str = "$") -> str:
    """Format cents for display: 123456 -> "$1,234.56", -500 -> "-$5.00"."""
    sign = "-" if cents < 0 else ""
    dollars, rem = divmod(abs(cents), 100)
    return f"{sign}{currency_symbol}{dollars:,}.{rem:02d}"

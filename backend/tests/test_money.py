import pytest

from app.services.money import format_cents, to_cents


@pytest.mark.parametrize(
    "amount, expected",
    [
        ("1,234.56", 123456),
        ("$12.30", 1230),
        (12.3, 1230),
        (0.1 + 0.2, 30),  # float noise must not leak into cents
        ("-45.005", -4501),  # half-up rounding away from zero
        (7, 700),
    ],
)
def test_to_cents(amount, expected):
    assert to_cents(amount) == expected


@pytest.mark.parametrize(
    "cents, expected",
    [(123456, "$1,234.56"), (-500, "-$5.00"), (0, "$0.00"), (5, "$0.05")],
)
def test_format_cents(cents, expected):
    assert format_cents(cents) == expected

from datetime import date

import pytest

from backend.plugin.rider_salary.enums import CycleType
from backend.plugin.rider_salary.utils.periods import compute_period_range


@pytest.mark.parametrize(
    ['any_date', 'expected'],
    [
        [date(2026, 9, 1), (date(2026, 9, 1), date(2026, 9, 15))],
        [date(2026, 9, 15), (date(2026, 9, 1), date(2026, 9, 15))],
        [date(2026, 9, 16), (date(2026, 9, 16), date(2026, 9, 30))],
        [date(2026, 9, 30), (date(2026, 9, 16), date(2026, 9, 30))],
        [date(2026, 2, 10), (date(2026, 2, 1), date(2026, 2, 15))],
        [date(2026, 2, 20), (date(2026, 2, 16), date(2026, 2, 28))],
        [date(2024, 2, 29), (date(2024, 2, 16), date(2024, 2, 29))],
    ],
)
def test_half_month_range(any_date: date, expected: tuple[date, date]) -> None:
    assert compute_period_range(CycleType.half_month, None, any_date) == expected


@pytest.mark.parametrize(
    ['any_date', 'expected'],
    [
        [date(2026, 9, 7), (date(2026, 9, 1), date(2026, 9, 30))],
        [date(2026, 2, 1), (date(2026, 2, 1), date(2026, 2, 28))],
        [date(2026, 2, 28), (date(2026, 2, 1), date(2026, 2, 28))],
        [date(2024, 2, 29), (date(2024, 2, 1), date(2024, 2, 29))],
        [date(2026, 1, 31), (date(2026, 1, 1), date(2026, 1, 31))],
    ],
)
def test_month_range(any_date: date, expected: tuple[date, date]) -> None:
    assert compute_period_range(CycleType.month, None, any_date) == expected
    assert compute_period_range('month', {'anchor_day': 26}, any_date) == expected


@pytest.mark.parametrize(
    ['any_date', 'anchor_day', 'expected'],
    [
        [date(2026, 9, 10), 26, (date(2026, 8, 26), date(2026, 9, 25))],
        [date(2026, 9, 26), 26, (date(2026, 9, 26), date(2026, 10, 25))],
        [date(2026, 9, 25), 26, (date(2026, 8, 26), date(2026, 9, 25))],
        [date(2026, 2, 10), 1, (date(2026, 2, 1), date(2026, 2, 28))],
        [date(2024, 2, 10), 1, (date(2024, 2, 1), date(2024, 2, 29))],
        [date(2026, 1, 31), 31, (date(2026, 1, 31), date(2026, 2, 27))],
        [date(2026, 2, 15), 31, (date(2026, 1, 31), date(2026, 2, 27))],
        [date(2026, 2, 28), 31, (date(2026, 2, 28), date(2026, 3, 30))],
        [date(2024, 2, 29), 31, (date(2024, 2, 29), date(2024, 3, 30))],
        [date(2024, 2, 10), 31, (date(2024, 1, 31), date(2024, 2, 28))],
        [date(2026, 3, 31), 31, (date(2026, 3, 31), date(2026, 4, 29))],
    ],
)
def test_custom_range(any_date: date, anchor_day: int, expected: tuple[date, date]) -> None:
    assert compute_period_range(CycleType.custom, {'anchor_day': anchor_day}, any_date) == expected


def test_custom_missing_config_equals_month() -> None:
    any_date = date(2026, 4, 12)
    assert compute_period_range(CycleType.custom, None, any_date) == (
        date(2026, 4, 1),
        date(2026, 4, 30),
    )


def test_invalid_anchor_day() -> None:
    with pytest.raises(ValueError, match='anchor_day'):
        compute_period_range(CycleType.custom, {'anchor_day': 32}, date(2026, 1, 1))

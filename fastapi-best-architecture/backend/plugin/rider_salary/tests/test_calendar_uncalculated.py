import inspect

from types import SimpleNamespace

from backend.plugin.rider_salary.service.calendar_service import (
    DAY_UNCALCULATED_HINT,
    ORDER_UNCALCULATED_HINT,
    WITHHOLD_HINT,
    CalendarService,
    build_day_uncalculated_hints,
    is_withholding_subject,
    order_uncalculated_hint,
)


def test_uncalculated_hints_when_no_cache_and_completed_orders() -> None:
    calculated, hint, withhold = build_day_uncalculated_hints(
        has_cache=False,
        completed_order_count=2,
        withhold_count=1,
    )
    assert calculated is False
    assert hint == DAY_UNCALCULATED_HINT
    assert '未算薪' in hint
    assert withhold == WITHHOLD_HINT
    assert '代扣不进日手工' in withhold


def test_cached_day_has_no_uncalculated_hint() -> None:
    calculated, hint, withhold = build_day_uncalculated_hints(
        has_cache=True,
        completed_order_count=2,
        withhold_count=1,
    )
    assert calculated is True
    assert hint is None
    assert withhold is None


def test_order_hint_when_no_cache_and_no_hits() -> None:
    assert order_uncalculated_hint(has_cache=False, has_hits=False) == ORDER_UNCALCULATED_HINT
    assert '尚未算薪' in ORDER_UNCALCULATED_HINT or '尚未进本次算薪' in ORDER_UNCALCULATED_HINT
    assert order_uncalculated_hint(has_cache=True, has_hits=False) is None
    assert order_uncalculated_hint(has_cache=False, has_hits=True) is None


def test_withholding_subject_excluded_from_uncalculated_manual() -> None:
    assert is_withholding_subject(SimpleNamespace(include_in_gross=False)) is True
    assert is_withholding_subject(SimpleNamespace(include_in_gross=True)) is False
    assert is_withholding_subject(None) is False


def test_build_day_does_not_persist_calculate() -> None:
    source = inspect.getsource(CalendarService.build_day)
    assert 'calculate_rider_period' not in source
    assert 'calculate_period' not in source
    assert 'persist=True' not in source

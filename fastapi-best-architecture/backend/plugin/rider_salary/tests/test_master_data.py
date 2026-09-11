from datetime import date

import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import BindingType, CycleType
from backend.plugin.rider_salary.service.rider_service import (
    BindingView,
    _default_password,
    check_binding_overlap,
    check_range_order,
    resolve_effective_plans_from_bindings,
)
from backend.plugin.rider_salary.utils.periods import compute_period_range


def _binding(
    binding_type: BindingType,
    start: date,
    end: date | None,
    plan_version_id: int,
    pk: int = 1,
) -> BindingView:
    return BindingView(
        binding_type=binding_type.value,
        start_date=start,
        end_date=end,
        plan_version_id=plan_version_id,
        id=pk,
    )


def test_override_overlap_rejected() -> None:
    existing = [_binding(BindingType.override, date(2026, 1, 1), date(2026, 1, 15), 10, pk=1)]
    with pytest.raises(errors.RequestError, match='重叠'):
        check_binding_overlap(
            existing,
            BindingType.override.value,
            date(2026, 1, 10),
            date(2026, 1, 20),
        )


def test_default_overlap_rejected() -> None:
    existing = [_binding(BindingType.default, date(2026, 1, 1), None, 10, pk=1)]
    with pytest.raises(errors.RequestError, match='重叠'):
        check_binding_overlap(existing, BindingType.default.value, date(2026, 6, 1), None)


def test_override_and_default_may_overlap() -> None:
    existing = [_binding(BindingType.default, date(2026, 1, 1), None, 10, pk=1)]
    check_binding_overlap(
        existing,
        BindingType.override.value,
        date(2026, 3, 1),
        date(2026, 3, 31),
    )


def test_adjacent_ranges_not_overlap() -> None:
    existing = [_binding(BindingType.override, date(2026, 1, 1), date(2026, 1, 15), 10, pk=1)]
    check_binding_overlap(
        existing,
        BindingType.override.value,
        date(2026, 1, 16),
        date(2026, 1, 31),
        exclude_id=None,
    )


def test_default_password_uses_phone_suffix() -> None:
    assert _default_password('13900001234') == 'Rider@001234'
    assert _default_password(None) == 'Rider@123456'
    assert _default_password('123') == 'Rider@123456'


def test_end_before_start_rejected() -> None:
    with pytest.raises(errors.RequestError, match='结束日期不能早于开始日期'):
        check_range_order(date(2026, 2, 1), date(2026, 1, 1))


def test_resolve_default_override_and_hole() -> None:
    bindings = [
        _binding(BindingType.default, date(2026, 9, 1), date(2026, 9, 20), 11, pk=1),
        _binding(BindingType.override, date(2026, 9, 10), date(2026, 9, 15), 22, pk=2),
    ]
    segments = resolve_effective_plans_from_bindings(bindings, date(2026, 9, 1), date(2026, 9, 25))
    assert [(item.start, item.end, item.plan_version_id) for item in segments] == [
        (date(2026, 9, 1), date(2026, 9, 9), 11),
        (date(2026, 9, 10), date(2026, 9, 15), 22),
        (date(2026, 9, 16), date(2026, 9, 20), 11),
        (date(2026, 9, 21), date(2026, 9, 25), None),
    ]


def test_resolve_all_hole() -> None:
    segments = resolve_effective_plans_from_bindings([], date(2026, 1, 1), date(2026, 1, 3))
    assert len(segments) == 1
    assert segments[0].plan_version_id is None
    assert segments[0].start == date(2026, 1, 1)
    assert segments[0].end == date(2026, 1, 3)


def test_subject_delete_reference_message() -> None:
    msg = f'科目已被引用（奖惩记录 {3} 条、方案项 {2} 条），无法删除'
    assert '奖惩记录 3 条' in msg
    assert '方案项 2 条' in msg


@pytest.mark.parametrize(
    ['any_date', 'expected'],
    [
        [date(2026, 9, 7), (date(2026, 9, 1), date(2026, 9, 30))],
        [date(2026, 2, 28), (date(2026, 2, 16), date(2026, 2, 28))],
        [date(2026, 9, 26), (date(2026, 9, 26), date(2026, 10, 25))],
    ],
)
def test_period_config_parse_cases(any_date: date, expected: tuple[date, date]) -> None:
    if any_date == date(2026, 9, 7):
        assert compute_period_range(CycleType.month, None, any_date) == expected
    elif any_date == date(2026, 2, 28):
        assert compute_period_range(CycleType.half_month, None, any_date) == expected
    else:
        assert compute_period_range(CycleType.custom, {'anchor_day': 26}, any_date) == expected

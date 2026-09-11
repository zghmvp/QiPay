from calendar import monthrange
from datetime import date, timedelta

from backend.plugin.rider_salary.enums import CycleType


def compute_period_range(
    cycle_type: CycleType | str,
    cycle_config: dict | None,
    any_date: date,
) -> tuple[date, date]:
    """
    计算任意日期所属结算周期的起止日期

    半月结为 1–15 / 16–月末；月结为自然月；自定义 ``{"anchor_day": N}`` 表示 N 日起至次月 N-1 日（N=1 等价月结）。
    当 N 大于当月天数时，起点钳制为当月最后一天（如 2 月 anchor=31 → 2/28 或 2/29 起，至 3/30）

    :param cycle_type: 周期类型
    :param cycle_config: 自定义周期配置
    :param any_date: 周期内任意日期
    :return:
    """
    kind = cycle_type if isinstance(cycle_type, CycleType) else CycleType(cycle_type)
    if kind == CycleType.half_month:
        return _half_month_range(any_date)
    if kind == CycleType.month:
        return _month_range(any_date)
    if kind == CycleType.custom:
        anchor_day = 1
        if isinstance(cycle_config, dict) and cycle_config.get('anchor_day') is not None:
            anchor_day = int(cycle_config['anchor_day'])
        if anchor_day < 1 or anchor_day > 31:
            raise ValueError('自定义周期 anchor_day 必须在 1–31 之间')
        if anchor_day == 1:
            return _month_range(any_date)
        return _custom_range(any_date, anchor_day)
    raise ValueError(f'不支持的结算周期类型：{cycle_type}')


def _month_last_day(year: int, month: int) -> int:
    return monthrange(year, month)[1]


def _month_range(any_date: date) -> tuple[date, date]:
    return date(any_date.year, any_date.month, 1), date(
        any_date.year,
        any_date.month,
        _month_last_day(any_date.year, any_date.month),
    )


def _half_month_range(any_date: date) -> tuple[date, date]:
    if any_date.day <= 15:
        return date(any_date.year, any_date.month, 1), date(any_date.year, any_date.month, 15)
    return date(any_date.year, any_date.month, 16), date(
        any_date.year,
        any_date.month,
        _month_last_day(any_date.year, any_date.month),
    )


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _clamp_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, _month_last_day(year, month)))


def _custom_range(any_date: date, anchor_day: int) -> tuple[date, date]:
    this_start = _clamp_day(any_date.year, any_date.month, anchor_day)
    if any_date >= this_start:
        start = this_start
        next_year, next_month = _shift_month(any_date.year, any_date.month, 1)
        end = _clamp_day(next_year, next_month, anchor_day) - timedelta(days=1)
        return start, end
    prev_year, prev_month = _shift_month(any_date.year, any_date.month, -1)
    start = _clamp_day(prev_year, prev_month, anchor_day)
    end = this_start - timedelta(days=1)
    return start, end

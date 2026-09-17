"""工作台异常订单 / 锁账倒计时语义单测。"""

from datetime import date

from backend.plugin.rider_salary.enums import OrderStatus, PeriodStatus
from backend.plugin.rider_salary.utils.order_attention import (
    ATTENTION_DURATION_SECONDS,
    DUE_PERIODS_TITLE,
    is_lock_due_period,
    lock_countdown_statuses,
    lock_due_countdown,
    order_attention_condition,
)


def test_attention_duration_is_60_minutes() -> None:
    assert ATTENTION_DURATION_SECONDS == 3600


def test_lock_countdown_includes_open_and_reopened() -> None:
    statuses = lock_countdown_statuses()
    assert PeriodStatus.open.value in statuses
    assert PeriodStatus.reopened.value in statuses
    assert PeriodStatus.locked.value not in statuses
    assert PeriodStatus.paid.value not in statuses


def test_lock_due_includes_overdue_open() -> None:
    today = date(2026, 9, 17)
    assert is_lock_due_period(status=PeriodStatus.open.value, end_date=date(2026, 9, 10), today=today)
    assert lock_due_countdown(end_date=date(2026, 9, 10), today=today)['countdown_text'] == '已过期未锁 7 天'
    assert DUE_PERIODS_TITLE == '锁账倒计时'


def test_order_attention_condition_builds() -> None:
    cond = order_attention_condition()
    compiled = str(cond.compile(compile_kwargs={'literal_binds': True}))
    lower = compiled.lower()
    assert 'deliver_time' in lower
    assert 'extract' in lower
    assert 'status' in lower
    assert OrderStatus.abnormal.value in lower
    assert OrderStatus.refunded.value in lower
    assert OrderStatus.completed.value in lower

"""异常订单（需关注）过滤条件：与工作台 attention 同源。"""

from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from backend.plugin.rider_salary.enums import OrderStatus, PeriodStatus
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod

# 配送时长超过 60 分钟视为超时（有送达时间才计入）
ATTENTION_DURATION_SECONDS = 3600

ATTENTION_REASON_ABNORMAL = '配送异常'
ATTENTION_REASON_REFUND = '退款'
ATTENTION_REASON_DURATION = '已完成且时长超过60分钟'


def order_attention_condition() -> ColumnElement[bool]:
    """配送异常 ∪ 已退款 ∪（已完成且有送达且时长>60min）。"""
    duration_sec = func.extract('epoch', RiderSalaryOrder.deliver_time - RiderSalaryOrder.order_time)
    return or_(
        RiderSalaryOrder.status == OrderStatus.abnormal.value,
        RiderSalaryOrder.status == OrderStatus.refunded.value,
        and_(
            RiderSalaryOrder.status == OrderStatus.completed.value,
            RiderSalaryOrder.deliver_time.is_not(None),
            RiderSalaryOrder.order_time.is_not(None),
            duration_sec > ATTENTION_DURATION_SECONDS,
        ),
    )


def _duration_seconds(order_time: datetime | None, deliver_time: datetime | None) -> float | None:
    if order_time is None or deliver_time is None:
        return None
    return (deliver_time - order_time).total_seconds()


def is_attention_order(
    *,
    status: str | None,
    order_time: datetime | None = None,
    deliver_time: datetime | None = None,
) -> bool:
    """与 order_attention_condition 同谓词的纯函数（导出排除 / 单测）。"""
    return attention_reason(status=status, order_time=order_time, deliver_time=deliver_time) is not None


def attention_reason(
    *,
    status: str | None,
    order_time: datetime | None = None,
    deliver_time: datetime | None = None,
) -> str | None:
    """需关注中文原因；非需关注返回 None。"""
    if status == OrderStatus.abnormal.value:
        return ATTENTION_REASON_ABNORMAL
    if status == OrderStatus.refunded.value:
        return ATTENTION_REASON_REFUND
    if status == OrderStatus.completed.value:
        seconds = _duration_seconds(order_time, deliver_time)
        if seconds is not None and seconds > ATTENTION_DURATION_SECONDS:
            return ATTENTION_REASON_DURATION
    return None


def keep_export_detail_row(*, exclude_attention: bool, order_id: int | None, attention_ids: set[int]) -> bool:
    """排除需关注只拿掉明细中对应订单行；无订单号的周期/按日行保留。"""
    if not exclude_attention or not order_id:
        return True
    return int(order_id) not in attention_ids


def attention_confession(*, count: int, excluded: bool) -> str | None:
    """导出文件中文承认句。count=0 不写。"""
    if count <= 0:
        return None
    if excluded:
        return f'已排除需关注 {count} 条；应发与实发未因排除改变'
    return f'本文件含需关注 {count} 条'


def attention_duration_minutes(order: Any) -> float | None:
    seconds = _duration_seconds(getattr(order, 'order_time', None), getattr(order, 'deliver_time', None))
    if seconds is None:
        return None
    return round(seconds / 60, 1)


def missing_delivery_condition() -> ColumnElement[bool]:
    """已完成且送达时间为空（与算薪缺送达硬失败同口径）。GET /orders?missing_delivery=1"""
    return and_(
        RiderSalaryOrder.status == OrderStatus.completed.value,
        RiderSalaryOrder.deliver_time.is_(None),
    )


LOCK_COUNTDOWN_HORIZON_DAYS = 3
DUE_PERIODS_TITLE = '锁账倒计时'


def lock_countdown_statuses() -> list[str]:
    """锁账倒计时：未锁的开放/补发中周期。"""
    return [PeriodStatus.open.value, PeriodStatus.reopened.value]


def lock_due_cutoff(today: date) -> date:
    """含当天与未来 HORIZON 天；已过期（end_date < today）也 ≤ cutoff。"""
    return today + timedelta(days=LOCK_COUNTDOWN_HORIZON_DAYS)


def is_lock_due_period(*, status: str | None, end_date: date | None, today: date) -> bool:
    """open|reopened 且 end_date ≤ today+3（含已过期未锁）；+10 天远周期不占待办。"""
    if end_date is None or status not in lock_countdown_statuses():
        return False
    return end_date <= lock_due_cutoff(today)


def lock_due_countdown(*, end_date: date, today: date) -> dict[str, Any]:
    """未到期「剩余 N 天」；已过期「已过期未锁 N 天」。"""
    days_left = (end_date - today).days
    if days_left < 0:
        overdue_days = -days_left
        return {
            'overdue': True,
            'days_left': days_left,
            'overdue_days': overdue_days,
            'countdown_text': f'已过期未锁 {overdue_days} 天',
        }
    return {
        'overdue': False,
        'days_left': days_left,
        'overdue_days': 0,
        'countdown_text': f'剩余 {days_left} 天',
    }


def due_periods_view_all_link(site_id: int | None) -> str:
    """查看全部：锁账倒计时筛，禁止只切无月份的 status=open。"""
    if site_id is not None:
        return f'/rider-salary/period?lock_due=1&site_id={int(site_id)}'
    return '/rider-salary/period?lock_due=1'


def due_period_sql_filters(today: date) -> list[ColumnElement[bool]]:
    """周期列表 lock_due=1 与工作台倒计时同一套谓词。"""
    return [
        RiderSalarySettlePeriod.status.in_(lock_countdown_statuses()),
        RiderSalarySettlePeriod.end_date <= lock_due_cutoff(today),
    ]


def abnormal_orders_landing_url(
    *,
    site_id: int | None,
    start: date,
    end: date,
    order_no: str | None = None,
) -> str:
    """工作台异常「查看全部」：attention 同源 + 本站本月窗。禁止只带 status=abnormal。"""
    month_key = f'{start:%Y-%m}'
    parts = [
        'attention=1',
        f'month={month_key}',
        f'date_from={start.isoformat()}',
        f'date_to={end.isoformat()}',
    ]
    if site_id is not None:
        parts.insert(1, f'site_id={int(site_id)}')
    if order_no:
        parts.append(f'order_no={quote(order_no, safe="")}')
    return '/rider-salary/order?' + '&'.join(parts)


def _period_order_filters(period: Any) -> list[ColumnElement[bool]]:
    filters = [
        RiderSalaryOrder.site_id == period.site_id,
        RiderSalaryOrder.biz_date >= period.start_date,
        RiderSalaryOrder.biz_date <= period.end_date,
        RiderSalaryOrder.deleted == 0,
        order_attention_condition(),
    ]
    rider_id = int(getattr(period, 'rider_id', 0) or 0)
    if rider_id:
        filters.append(RiderSalaryOrder.rider_id == rider_id)
    return filters


async def count_period_attention_orders(db: AsyncSession, period: Any) -> int:
    """周期窗口内需关注订单数（站点级含全站，骑手级只计该骑手）。"""
    total = await db.scalar(select(func.count()).select_from(RiderSalaryOrder).where(*_period_order_filters(period)))
    return int(total or 0)


async def list_period_attention_orders(db: AsyncSession, period: Any) -> list[RiderSalaryOrder]:
    """周期窗口内需关注订单，供导出说明表。"""
    rows = await db.scalars(
        select(RiderSalaryOrder).where(*_period_order_filters(period)).order_by(RiderSalaryOrder.id.asc())
    )
    return list(rows.all())

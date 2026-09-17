"""异常订单（需关注）过滤条件：与工作台 attention 同源。"""

from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from backend.plugin.rider_salary.enums import OrderStatus, PeriodStatus
from backend.plugin.rider_salary.model.order import RiderSalaryOrder

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


def lock_countdown_statuses() -> list[str]:
    """锁账倒计时：未锁的开放/补发中周期。"""
    return [PeriodStatus.open.value, PeriodStatus.reopened.value]


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

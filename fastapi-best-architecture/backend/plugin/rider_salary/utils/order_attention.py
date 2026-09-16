"""异常订单（需关注）过滤条件：与工作台 attention 同源。"""

from sqlalchemy import and_, func, or_
from sqlalchemy.sql.elements import ColumnElement

from backend.plugin.rider_salary.enums import OrderStatus, PeriodStatus
from backend.plugin.rider_salary.model.order import RiderSalaryOrder

# 配送时长超过 60 分钟视为超时（有送达时间才计入）
ATTENTION_DURATION_SECONDS = 3600


def order_attention_condition() -> ColumnElement[bool]:
    """配送异常 ∪ 已退款 ∪（有送达且时长>60min）。"""
    duration_sec = func.extract('epoch', RiderSalaryOrder.deliver_time - RiderSalaryOrder.order_time)
    return or_(
        RiderSalaryOrder.status.in_([OrderStatus.abnormal.value, OrderStatus.refunded.value]),
        and_(
            RiderSalaryOrder.deliver_time.is_not(None),
            RiderSalaryOrder.order_time.is_not(None),
            duration_sec > ATTENTION_DURATION_SECONDS,
        ),
    )


def lock_countdown_statuses() -> list[str]:
    """锁账倒计时：未锁的开放/补发中周期。"""
    return [PeriodStatus.open.value, PeriodStatus.reopened.value]

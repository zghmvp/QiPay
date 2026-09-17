import datetime as dt

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase


class CalendarPeriodChip(SchemaBase):
    """日历顶部周期状态"""

    id: int = Field(description='周期 ID')
    range: str = Field(description='区间展示')
    status: str = Field(description='周期状态')


class CalendarMonthSummary(SchemaBase):
    """日历月汇总"""

    order_count: int = Field(description='本月累计单量')
    valid_order_count: int = Field(description='本月有效单量')
    gross: Decimal = Field(description='应发')
    bonus: Decimal = Field(description='奖')
    penalty: Decimal = Field(description='惩')
    deduction_total: Decimal = Field(description='代扣')
    advance_deduction: Decimal = Field(description='预支抵扣')
    net: Decimal = Field(description='实发')
    periods: list[CalendarPeriodChip] = Field(default_factory=list, description='涉及周期及状态')
    stale: bool = Field(False, description='是否存在需重算结果')


class CalendarDayItem(SchemaBase):
    """日历日格"""

    date: dt.date = Field(description='日期')
    order_count: int = Field(description='单量')
    valid_order_count: int = Field(description='有效单量')
    net_adjust: Decimal = Field(description='手工奖惩净额')
    subjects: list[str] = Field(default_factory=list, description='科目摘要')
    plan_version_id: int | None = Field(None, description='方案版本 ID')
    plan_short_name: str | None = Field(None, description='方案短名')
    plan_color: str | None = Field(None, description='色带颜色')
    day_status: str = Field(description='日状态')
    period_id: int | None = Field(None, description='所属周期 ID')
    period_status: str | None = Field(None, description='所属周期状态')
    is_locked: bool = Field(False, description='是否锁账')


class CalendarPlanBand(SchemaBase):
    """方案色带区间（已按月裁剪）"""

    plan_version_id: int | None = Field(None, description='方案版本 ID')
    short_name: str | None = Field(None, description='短名')
    color: str | None = Field(None, description='颜色')
    start: dt.date = Field(description='开始日期')
    end: dt.date = Field(description='结束日期')


class GetCalendarMonth(SchemaBase):
    """月历"""

    month: str = Field(description='月份 YYYY-MM')
    summary: CalendarMonthSummary = Field(description='月汇总')
    days: list[CalendarDayItem] = Field(default_factory=list, description='日格')
    plan_bands: list[CalendarPlanBand] = Field(default_factory=list, description='方案色带')


class CalendarPlanInfo(SchemaBase):
    """当日生效方案"""

    version_id: int | None = Field(None, description='版本 ID')
    plan_name: str | None = Field(None, description='方案名称')
    short_name: str | None = Field(None, description='短名')
    version_no: int | None = Field(None, description='版本号')
    mode_tag: str | None = Field(None, description='计薪模式')


class CalendarPeriodInfo(SchemaBase):
    """当日归属周期"""

    id: int | None = Field(None, description='周期 ID')
    range: str | None = Field(None, description='区间')
    status: str | None = Field(None, description='状态')


class CalendarHitDetail(SchemaBase):
    """订单命中明细"""

    subject: str = Field(description='科目')
    amount: Decimal = Field(description='金额')
    calc_trace: dict[str, Any] | None = Field(None, description='计算过程')


class CalendarDayOrder(SchemaBase):
    """当日订单"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='订单 ID')
    order_no: str = Field(description='订单号')
    distance_km: Decimal = Field(description='配送距离')
    weight_jin: Decimal = Field(description='商品重量')
    order_time: datetime = Field(description='下单时间')
    deliver_time: datetime | None = Field(None, description='送达时间')
    status: str = Field(description='订单状态')
    amount: Decimal | None = Field(None, description='订单金额')
    details: list[CalendarHitDetail] = Field(default_factory=list, description='命中明细')


class CalendarDailyItem(SchemaBase):
    """按日项明细"""

    subject: str = Field(description='科目')
    name: str | None = Field(None, description='项名称')
    amount: Decimal = Field(description='金额')
    calc_trace: dict[str, Any] | None = Field(None, description='计算过程')


class CalendarAdjustmentItem(SchemaBase):
    """当日手工奖惩"""

    id: int = Field(description='奖惩 ID')
    subject: str = Field(description='科目')
    direction: str = Field(description='方向')
    amount: Decimal = Field(description='金额（带符号）')
    remark: str = Field(description='备注')


class CalendarDayTotals(SchemaBase):
    """当日合计"""

    order_count: int = Field(description='单量')
    formula_amount: Decimal = Field(description='公式金额')
    manual_bonus: Decimal = Field(description='手工奖')
    manual_penalty: Decimal = Field(description='手工惩')
    net: Decimal = Field(description='当日净额')


class GetCalendarDayDetail(SchemaBase):
    """日详情"""

    date: dt.date = Field(description='日期')
    plan: CalendarPlanInfo | None = Field(None, description='当日方案')
    period: CalendarPeriodInfo | None = Field(None, description='当日周期')
    is_holiday: bool = Field(False, description='是否节假日')
    day_status: str = Field(description='日状态')
    orders: list[CalendarDayOrder] = Field(default_factory=list, description='订单')
    daily_items: list[CalendarDailyItem] = Field(default_factory=list, description='按日项')
    adjustments: list[CalendarAdjustmentItem] = Field(default_factory=list, description='手工奖惩')
    totals: CalendarDayTotals = Field(description='合计')

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase


class GetPayrollDailyDetail(SchemaBase):
    """日汇总"""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = Field(None, description='日汇总 ID')
    rider_id: int = Field(description='骑手 ID')
    biz_date: date = Field(description='业务日期')
    period_id: int | None = Field(None, description='结算周期 ID')
    plan_version_id: int | None = Field(None, description='当日方案版本')
    order_count: int = Field(description='单量')
    valid_order_count: int = Field(description='有效单量')
    formula_amount: Decimal = Field(description='公式金额')
    manual_bonus: Decimal = Field(description='手工奖')
    manual_penalty: Decimal = Field(description='手工惩')
    net_adjust: Decimal = Field(description='手工奖惩净额')
    day_status: str = Field(description='日状态')


class GetPayrollDetailItem(SchemaBase):
    """薪资明细"""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = Field(None, description='明细 ID')
    payroll_id: int | None = Field(None, description='薪资单 ID')
    rider_id: int = Field(description='骑手 ID')
    biz_date: date | None = Field(None, description='业务日期')
    stage: str = Field(description='计算阶段')
    plan_version_id: int | None = Field(None, description='方案版本 ID')
    plan_item_id: int | None = Field(None, description='方案项 ID')
    subject_id: int = Field(description='科目 ID')
    order_id: int | None = Field(None, description='订单 ID')
    amount: Decimal = Field(description='金额（带符号）')
    include_in_gross: bool = Field(description='是否计入应发')
    source: str = Field(description='来源')
    calc_trace: dict[str, Any] | None = Field(None, description='计算过程')
    name: str | None = Field(None, description='项名称')
    order_no: str | None = Field(None, description='订单号')


class GetPayrollSummary(SchemaBase):
    """薪资单汇总"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='薪资单 ID')
    period_id: int = Field(description='结算周期 ID')
    rider_id: int = Field(description='骑手 ID')
    kind: str = Field(description='类型')
    status: str = Field(description='状态')
    calc_version: int = Field(description='计算轮次')
    stale: bool = Field(description='需重算')
    reversed: bool = Field(description='已被反冲')
    warnings: list[str] | None = Field(None, description='计算告警')
    order_count: int = Field(description='单量')
    valid_order_count: int = Field(description='有效单量')
    per_order_total: Decimal = Field(description='逐单项合计')
    daily_total: Decimal = Field(description='按日项合计')
    period_total: Decimal = Field(description='周期项合计')
    bonus_total: Decimal = Field(description='手工奖合计')
    penalty_total: Decimal = Field(description='手工惩合计')
    gross: Decimal = Field(description='应发')
    deduction_total: Decimal = Field(description='代扣合计')
    advance_deduction: Decimal = Field(description='预支抵扣')
    net: Decimal = Field(description='实发')
    plan_version_ids: list[int] | None = Field(None, description='本期方案版本集合')
    reversed_of_id: int | None = Field(None, description='反冲对象 ID')
    calc_time: datetime | None = Field(None, description='计算时间')
    calc_by: int | None = Field(None, description='计算人 ID')
    created_time: datetime | None = Field(None, description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')


class GetPayrollGroupedDetail(GetPayrollSummary):
    """薪资单详情（明细按阶段分组）"""

    details: dict[str, list[GetPayrollDetailItem]] = Field(default_factory=dict, description='按阶段分组的明细')
    dailies: list[GetPayrollDailyDetail] = Field(default_factory=list, description='日汇总列表')

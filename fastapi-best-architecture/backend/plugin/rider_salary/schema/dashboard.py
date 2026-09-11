import datetime as dt

from decimal import Decimal
from typing import Any

from pydantic import Field

from backend.common.schema import SchemaBase


class DashboardCards(SchemaBase):
    """工作台卡片"""

    on_job_riders: int = Field(description='在职骑手数')
    month_order_count: int = Field(description='本月单量')
    month_valid_order_count: int = Field(description='本月有效单量')
    estimated_gross: Decimal = Field(description='预计应发合计')
    pending_advances: int = Field(description='待审核预支数')
    to_pay_advances: int = Field(description='待发放预支数')


class DashboardAttentionBlock(SchemaBase):
    """工作台待办模块"""

    key: str = Field(description='模块标识')
    title: str = Field(description='标题')
    count: int = Field(description='数量')
    items: list[dict[str, Any]] = Field(default_factory=list, description='条目（最多 10 条）')
    link: str = Field(description='前端跳转')


class DashboardTrendPoint(SchemaBase):
    """近 30 天趋势点"""

    date: dt.date = Field(description='日期')
    order_count: int = Field(description='单量')
    formula_amount: Decimal = Field(description='逐单金额')


class DashboardRiderRank(SchemaBase):
    """骑手单量排行"""

    rider_id: int = Field(description='骑手 ID')
    job_no: str = Field(description='工号')
    name: str = Field(description='姓名')
    order_count: int = Field(description='本月单量')


class DashboardTopRiders(SchemaBase):
    """本月单量排行"""

    top: list[DashboardRiderRank] = Field(default_factory=list, description='单量 Top 10')
    bottom: list[DashboardRiderRank] = Field(default_factory=list, description='单量最低 5 名')


class GetDashboardSummary(SchemaBase):
    """工作台汇总"""

    month: str = Field(description='月份 YYYY-MM')
    cards: DashboardCards = Field(description='卡片')
    attention: list[DashboardAttentionBlock] = Field(default_factory=list, description='待办')
    trend: list[DashboardTrendPoint] = Field(default_factory=list, description='近 30 天趋势')
    top_riders: DashboardTopRiders = Field(description='骑手排行')

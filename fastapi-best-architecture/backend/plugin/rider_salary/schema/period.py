from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import ConfigDict, Field, computed_field, field_validator

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import CycleType, PeriodStatus
from backend.plugin.rider_salary.schema.payroll import GetPayrollSummary


def _enum_label(enum_cls: type, value: Any) -> str:
    try:
        return enum_cls(value).label
    except ValueError:
        return str(value)


class GeneratePeriodParam(SchemaBase):
    """生成结算周期参数"""

    site_id: int = Field(description='站点 ID')
    month: str = Field(description='目标月份，格式 YYYY-MM')

    @field_validator('month')
    @classmethod
    def validate_month(cls, value: str) -> str:
        text = (value or '').strip()
        parts = text.split('-')
        if len(parts) != 2 or len(parts[0]) != 4:
            raise ValueError('月份格式应为 YYYY-MM')
        try:
            year = int(parts[0])
            month = int(parts[1])
        except ValueError as exc:
            raise ValueError('月份格式应为 YYYY-MM') from exc
        if month < 1 or month > 12:
            raise ValueError('月份格式应为 YYYY-MM')
        if year < 2000 or year > 2100:
            raise ValueError('月份格式应为 YYYY-MM')
        return f'{year:04d}-{month:02d}'


class CalculatePeriodParam(SchemaBase):
    """算薪参数"""

    rider_ids: list[int] | None = Field(None, description='指定骑手 ID，空表示周期内全部')


class LockPeriodParam(SchemaBase):
    """锁账参数"""

    reason: str = Field(description='锁账原因')


class MarkPaidPeriodParam(SchemaBase):
    """标记发薪参数"""

    reason: str | None = Field(None, description='操作原因')


class ReversePeriodParam(SchemaBase):
    """反冲补发参数"""

    reason: str = Field(description='反冲原因')


class PeriodSchemaBase(SchemaBase):
    """结算周期基础字段"""

    site_id: int = Field(description='站点 ID')
    rider_id: int = Field(description='骑手 ID，0 表示站点级')
    cycle_type: str = Field(description='周期类型')
    start_date: date = Field(description='开始日期')
    end_date: date = Field(description='结束日期')
    status: str = Field(description='状态')
    remark: str | None = Field(None, description='备注')


class GetPeriodDetail(PeriodSchemaBase):
    """结算周期详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='周期 ID')
    locked_by: int | None = Field(None, description='锁账人 ID')
    locked_time: datetime | None = Field(None, description='锁账时间')
    paid_by: int | None = Field(None, description='发薪标记人 ID')
    paid_time: datetime | None = Field(None, description='发薪标记时间')
    reopened_by: int | None = Field(None, description='反冲人 ID')
    reopened_time: datetime | None = Field(None, description='反冲时间')
    created_time: datetime | None = Field(None, description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')
    site_name: str | None = Field(None, description='站点名称')
    site_code: str | None = Field(None, description='站点编码')
    rider_job_no: str | None = Field(None, description='骑手工号')
    rider_name: str | None = Field(None, description='骑手姓名')

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_label(self) -> str:
        """状态中文"""
        return _enum_label(PeriodStatus, self.status)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cycle_type_label(self) -> str:
        """周期类型中文"""
        return _enum_label(CycleType, self.cycle_type)


class GetPeriodPayrollItem(GetPayrollSummary):
    """周期内薪资单摘要（含骑手信息与反冲链）"""

    job_no: str | None = Field(None, description='工号')
    rider_name: str | None = Field(None, description='姓名')


class GetPeriodWithPayrolls(GetPeriodDetail):
    """周期详情 + 全部薪资单"""

    payrolls: list[GetPeriodPayrollItem] = Field(default_factory=list, description='薪资单摘要（含反冲/补发链）')
    rider_count: int = Field(0, description='骑手数')
    payroll_count: int = Field(0, description='薪资单数')
    stale_count: int = Field(0, description='需重算数')
    gross_total: Decimal = Field(Decimal('0.00'), description='应发合计')
    net_total: Decimal = Field(Decimal('0.00'), description='实发合计')
    kind_counts: dict[str, int] = Field(default_factory=dict, description='单据类型分布')


class GetPeriodListItem(GetPeriodDetail):
    """周期列表项（含统计）"""

    rider_count: int = Field(0, description='骑手数')
    payroll_count: int = Field(0, description='薪资单数')
    stale_count: int = Field(0, description='需重算数')
    gross_total: Decimal = Field(Decimal('0.00'), description='应发合计')
    net_total: Decimal = Field(Decimal('0.00'), description='实发合计')
    kind_counts: dict[str, int] = Field(default_factory=dict, description='单据类型分布')


class GetGeneratedPeriodItem(SchemaBase):
    """生成周期清单项"""

    id: int = Field(description='周期 ID')
    site_id: int = Field(description='站点 ID')
    rider_id: int = Field(description='骑手 ID，0 表示站点级')
    cycle_type: str = Field(description='周期类型')
    start_date: date = Field(description='开始日期')
    end_date: date = Field(description='结束日期')
    status: str = Field(description='状态')
    created: bool = Field(description='本次是否新生成')


class GeneratePeriodResult(SchemaBase):
    """生成周期结果"""

    site_id: int = Field(description='站点 ID')
    month: str = Field(description='目标月份')
    items: list[GetGeneratedPeriodItem] = Field(description='生成清单')
    created_count: int = Field(description='新生成数量')
    skipped_count: int = Field(description='已存在跳过数量')


class CalculatePeriodResult(SchemaBase):
    """算薪结果"""

    calculated: int = Field(description='本次计算骑手数')
    warnings: list[str] = Field(default_factory=list, description='告警')
    queued: bool = Field(False, description='是否转入后台')


class ReversePeriodResult(SchemaBase):
    """反冲补发结果"""

    reversal_count: int = Field(description='反冲单数量')
    reversal_net_total: Decimal = Field(description='反冲金额合计')


class ReversePreflightResult(SchemaBase):
    """反冲补发预检（只计数，不改反冲谓词）"""

    period_id: int = Field(description='周期 ID')
    reversal_count: int = Field(description='将生成的反冲薪资单数')
    rider_count: int = Field(description='涉及骑手数（本周期将实际反冲的已定稿/已发薪条）')
    confirm_hint: str = Field(description='确认中文摘要，含单数与人数')


class GetPeriodForDateResult(SchemaBase):
    """按日期查询周期"""

    exists: bool = Field(description='是否已有周期实例')
    site_id: int = Field(description='站点 ID')
    rider_id: int = Field(description='解析后的周期骑手 ID，0 为站点级')
    cycle_type: str = Field(description='周期类型')
    start_date: date = Field(description='开始日期')
    end_date: date = Field(description='结束日期')
    period: GetPeriodDetail | None = Field(None, description='已存在的周期')

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import ConfigDict, Field, computed_field, field_validator

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import CycleType, PeriodStatus, RecalcJobStatus
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

    rider_ids: list[int] | None = Field(
        None,
        description='指定骑手 ID；未选（空或省略）= 计算本周期全部骑手；非空只算选中的人',
    )


class LockPeriodParam(SchemaBase):
    """锁账参数"""

    reason: str = Field(description='锁账原因')


class LockPreflightResult(SchemaBase):
    """锁账预检（站点级含决策 29 跳过人数）"""

    freeze_order_count: int = Field(description='本锁将改写 is_locked 的订单数')
    freeze_adjustment_count: int = Field(description='本锁将改写 is_locked 的奖惩数')
    freeze_payroll_count: int = Field(description='本锁将冻结的薪资单数')
    lock_rider_count: int = Field(description='将被本锁改写的骑手数（已扣除决策29骑手级覆盖）')
    skip_rider_count: int = Field(description='决策29跳过的骑手级覆盖人数')
    skip_hint: str = Field(description='跳过说明，如「跳过骑手级覆盖 0 人」')
    confirm_hint: str = Field(description='锁确认中文摘要')
    is_site_level: bool = Field(description='是否站点级周期（rider_id=0）')


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


class CalcPrecheckDeeplink(SchemaBase):
    """预检/失败深链"""

    path: str = Field(description='前端路径')
    query: dict[str, str] | None = Field(None, description='查询参数')


class CalculateRiderFailure(SchemaBase):
    """单骑手算薪失败"""

    rider_id: int = Field(description='骑手 ID')
    job_no: str | None = Field(None, description='工号')
    errors: list[str] = Field(default_factory=list, description='错误列表')
    code: str | None = Field(None, description='失败码：missing_delivery / no_plan_with_orders / never_calculated')
    deeplink: CalcPrecheckDeeplink | None = Field(None, description='修复深链')


class GetPeriodWithPayrolls(GetPeriodDetail):
    """周期详情 + 全部薪资单"""

    payrolls: list[GetPeriodPayrollItem] = Field(default_factory=list, description='薪资单摘要（含反冲/补发链）')
    rider_count: int = Field(0, description='骑手数')
    payroll_count: int = Field(0, description='薪资单数')
    stale_count: int = Field(0, description='需重算数')
    gross_total: Decimal = Field(Decimal('0.00'), description='应发合计')
    net_total: Decimal = Field(Decimal('0.00'), description='实发合计')
    kind_counts: dict[str, int] = Field(default_factory=dict, description='单据类型分布')
    last_calc_failures: list[CalculateRiderFailure] = Field(
        default_factory=list,
        description='最近一次算薪失败清单',
    )
    last_calc_status: str | None = Field(None, description='最近一次算薪态 queued/running/done/failed')
    last_calc_status_message: str | None = Field(None, description='最近一次算薪态说明')
    last_calc_success_ids: list[int] = Field(
        default_factory=list,
        description='最近一次算薪成功骑手 ID（F5 还原本次成功表，避免 toast 丢掉失败）',
    )
    attention_order_count: int = Field(0, description='周期内需关注订单数（与工作台 attention 同谓词）')
    booked_adjustment_count: int = Field(0, description='本周期已入账奖惩条数')
    unbooked_adjustment_count: int = Field(0, description='窗口内未入账奖惩条数')
    attention_adjustment_count: int = Field(0, description='与需关注同日同骑手的奖惩条数（默认仍导出）')

    @computed_field  # type: ignore[prop-decorator]
    @property
    def last_calc_status_label(self) -> str | None:
        """算薪态中文：排队中 / 计算中 / 完成 / 失败"""
        if not self.last_calc_status:
            return None
        try:
            return RecalcJobStatus(self.last_calc_status).label
        except ValueError:
            return self.last_calc_status


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

    calculated: int = Field(description='本次计算成功骑手数')
    warnings: list[str] = Field(default_factory=list, description='非阻断提示（如转入后台）')
    failed: list[CalculateRiderFailure] = Field(default_factory=list, description='失败骑手清单')
    calculated_rider_ids: list[int] = Field(default_factory=list, description='本次成功骑手 ID')
    queued: bool = Field(False, description='是否转入后台')
    calc_status: str | None = Field(None, description='算薪态 queued/running/done/failed')
    calc_status_label: str | None = Field(None, description='算薪态中文')
    sync_limit: int = Field(200, description='同步算薪骑手上限，超出转入后台')
    target_rider_count: int = Field(0, description='本次目标骑手数')
    unselected_means_all: str = Field('未选 = 计算本周期全部骑手', description='未选骑手时的计算范围')

    @computed_field  # type: ignore[prop-decorator]
    @property
    def failed_count(self) -> int:
        """失败人数；列表算薪不得只 toast 成功人数而丢掉 failed[]"""
        return len(self.failed)


class CalcPrecheckBlocker(SchemaBase):
    """算前硬风险条目"""

    code: str = Field(description='阻断码')
    rider_id: int = Field(description='骑手 ID')
    job_no: str | None = Field(None, description='工号')
    rider_name: str | None = Field(None, description='姓名')
    messages: list[str] = Field(default_factory=list, description='中文说明')
    deeplink: CalcPrecheckDeeplink | None = Field(None, description='修复深链')


class CalcPrecheckWarning(SchemaBase):
    """算前警告条目"""

    code: str = Field(description='警告码')
    messages: list[str] = Field(default_factory=list, description='中文说明')
    deeplink: CalcPrecheckDeeplink | None = Field(None, description='相关深链')


class CalcPrecheckResult(SchemaBase):
    """周期算薪预检结果"""

    period_id: int = Field(description='周期 ID')
    can_run: bool = Field(description='周期级是否允许调用 calculate')
    blockers: list[CalcPrecheckBlocker] = Field(default_factory=list, description='骑手级硬风险')
    warnings: list[CalcPrecheckWarning] = Field(default_factory=list, description='非阻断警告')
    eligible_rider_count: int = Field(description='默认将计算的骑手数')
    stale_count: int = Field(0, description='需重算薪资单数')
    calc_status: str | None = Field(None, description='最近一次算薪态 queued/running/done/failed')
    calc_status_label: str | None = Field(None, description='算薪态中文')
    calc_status_message: str | None = Field(None, description='算薪态说明')
    sync_limit: int = Field(200, description='同步算薪骑手上限，超出转入后台；CDP 可压低配置')
    attention_order_count: int = Field(0, description='周期内需关注订单数')
    unselected_means_all: str = Field('未选 = 计算本周期全部骑手', description='未选骑手时的计算范围')


class CalcRiderOption(SchemaBase):
    """算薪骑手选项"""

    id: int = Field(description='骑手 ID')
    job_no: str = Field(description='工号')
    name: str = Field(description='姓名')


class CalcRiderPageResult(SchemaBase):
    """算薪骑手搜索分页；未选=全量，可见列表不是全集时 truncated_hint 提示搜索"""

    items: list[CalcRiderOption] = Field(default_factory=list, description='当前页骑手')
    total: int = Field(description='匹配总数')
    page: int = Field(description='页码')
    size: int = Field(description='每页数量，最大 200')
    listed_count: int = Field(description='本页条数')
    truncated: bool = Field(description='可见列表是否不是全集')
    truncated_hint: str | None = Field(None, description='仅列出前 N 人，其余请搜索')
    unselected_means_all: str = Field('未选 = 计算本周期全部骑手', description='未选骑手时的计算范围')


class ReversePeriodResult(SchemaBase):
    """反冲补发结果"""

    reversal_count: int = Field(description='反冲单数量')
    reversal_net_total: Decimal = Field(description='反冲金额合计')


class GetPeriodForDateResult(SchemaBase):
    """按日期查询周期"""

    exists: bool = Field(description='是否已有周期实例')
    site_id: int = Field(description='站点 ID')
    rider_id: int = Field(description='解析后的周期骑手 ID，0 为站点级')
    cycle_type: str = Field(description='周期类型')
    start_date: date = Field(description='开始日期')
    end_date: date = Field(description='结束日期')
    period: GetPeriodDetail | None = Field(None, description='已存在的周期')

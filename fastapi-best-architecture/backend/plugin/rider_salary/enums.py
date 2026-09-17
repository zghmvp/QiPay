from enum import Enum
from typing import ClassVar, TypeVar

from backend.common.enums import StrEnum

_E = TypeVar('_E', bound=Enum)


class LabeledStrEnum(StrEnum):
    """带中文标签的字符串枚举"""

    LABELS: ClassVar[dict[str, str]]

    @property
    def label(self) -> str:
        """中文名称"""
        return type(self).LABELS[self.value]


def _bind_labels(enum_cls: type[_E], labels: dict[str, str]) -> type[_E]:
    """在类体外部绑定 LABELS，避免被 StrEnum 当成成员"""
    enum_cls.LABELS = labels
    return enum_cls


class CycleType(LabeledStrEnum):
    """站点 / 骑手结算周期类型"""

    half_month = 'half_month'
    month = 'month'
    custom = 'custom'


_bind_labels(
    CycleType,
    {
        CycleType.half_month: '半月结',
        CycleType.month: '月结',
        CycleType.custom: '自定义',
    },
)


class EnableStatus(LabeledStrEnum):
    """启用 / 停用"""

    enable = 'enable'
    disable = 'disable'


_bind_labels(EnableStatus, {EnableStatus.enable: '启用', EnableStatus.disable: '停用'})


class ManagerRole(LabeledStrEnum):
    """站点负责人角色"""

    owner = 'owner'
    deputy = 'deputy'


_bind_labels(ManagerRole, {ManagerRole.owner: '负责人', ManagerRole.deputy: '副负责人'})


class EmployType(LabeledStrEnum):
    """用工类型"""

    part_time = 'part_time'
    full_time = 'full_time'


_bind_labels(EmployType, {EmployType.part_time: '兼职', EmployType.full_time: '全职'})


class RiderStatus(LabeledStrEnum):
    """骑手状态"""

    on_job = 'on_job'
    resigned = 'resigned'


_bind_labels(RiderStatus, {RiderStatus.on_job: '在职', RiderStatus.resigned: '离职'})


class BindingType(LabeledStrEnum):
    """方案绑定类型"""

    default = 'default'
    override = 'override'


_bind_labels(BindingType, {BindingType.default: '默认', BindingType.override: '区间覆盖'})


class SubjectDirection(LabeledStrEnum):
    """科目方向"""

    bonus = 'bonus'
    penalty = 'penalty'


_bind_labels(SubjectDirection, {SubjectDirection.bonus: '奖', SubjectDirection.penalty: '惩'})


class FeeMode(LabeledStrEnum):
    """计费方式"""

    fixed = 'fixed'
    formula = 'formula'


_bind_labels(FeeMode, {FeeMode.fixed: '定额', FeeMode.formula: '按公式'})


class EntryGranularity(LabeledStrEnum):
    """入账粒度"""

    daily = 'daily'
    period = 'period'
    both = 'both'


_bind_labels(
    EntryGranularity,
    {
        EntryGranularity.daily: '按日',
        EntryGranularity.period: '按周期',
        EntryGranularity.both: '按日或按周期',
    },
)


class PlanVersionStatus(LabeledStrEnum):
    """方案版本状态"""

    draft = 'draft'
    active = 'active'
    disabled = 'disabled'
    voided = 'voided'


_bind_labels(
    PlanVersionStatus,
    {
        PlanVersionStatus.draft: '草稿',
        PlanVersionStatus.active: '启用',
        PlanVersionStatus.disabled: '停用',
        PlanVersionStatus.voided: '已作废',
    },
)


class PlanModeTag(LabeledStrEnum):
    """计薪模式标签（仅展示分类）"""

    per_order = 'per_order'
    base_plus_commission = 'base_plus_commission'
    commission = 'commission'
    guarantee_plus_commission = 'guarantee_plus_commission'
    custom = 'custom'


_bind_labels(
    PlanModeTag,
    {
        PlanModeTag.per_order: '纯按单',
        PlanModeTag.base_plus_commission: '底薪加提成',
        PlanModeTag.commission: '纯提成',
        PlanModeTag.guarantee_plus_commission: '保底加提成',
        PlanModeTag.custom: '自定义',
    },
)


class CalcStage(LabeledStrEnum):
    """计算阶段"""

    per_order = 'per_order'
    daily = 'daily'
    period = 'period'


_bind_labels(
    CalcStage,
    {
        CalcStage.per_order: '逐单',
        CalcStage.daily: '按日',
        CalcStage.period: '按周期',
    },
)


class OrderStatus(LabeledStrEnum):
    """订单状态"""

    completed = 'completed'
    cancelled = 'cancelled'
    abnormal = 'abnormal'
    refunded = 'refunded'


_bind_labels(
    OrderStatus,
    {
        OrderStatus.completed: '已完成',
        OrderStatus.cancelled: '已取消',
        OrderStatus.abnormal: '配送异常',
        OrderStatus.refunded: '已退款',
    },
)


class OrderSource(LabeledStrEnum):
    """订单来源"""

    import_ = 'import'
    manual = 'manual'


_bind_labels(OrderSource, {OrderSource.import_: '导入', OrderSource.manual: '补录'})


class ImportBatchStatus(LabeledStrEnum):
    """导入批次状态"""

    processing = 'processing'
    success = 'success'
    partial_failed = 'partial_failed'
    failed = 'failed'


_bind_labels(
    ImportBatchStatus,
    {
        ImportBatchStatus.processing: '处理中',
        ImportBatchStatus.success: '成功',
        ImportBatchStatus.partial_failed: '部分失败',
        ImportBatchStatus.failed: '失败',
    },
)


class PeriodStatus(LabeledStrEnum):
    """结算周期状态"""

    open = 'open'
    locked = 'locked'
    paid = 'paid'
    reopened = 'reopened'


_bind_labels(
    PeriodStatus,
    {
        PeriodStatus.open: '开放',
        PeriodStatus.locked: '已锁账',
        PeriodStatus.paid: '已发薪',
        PeriodStatus.reopened: '补发中',
    },
)


class PayrollKind(LabeledStrEnum):
    """薪资单类型"""

    normal = 'normal'
    reversal = 'reversal'
    supplement = 'supplement'


_bind_labels(
    PayrollKind,
    {
        PayrollKind.normal: '正常',
        PayrollKind.reversal: '反冲',
        PayrollKind.supplement: '补发',
    },
)


class PayrollStatus(LabeledStrEnum):
    """薪资单状态"""

    draft = 'draft'
    finalized = 'finalized'
    paid = 'paid'
    voided = 'voided'


_bind_labels(
    PayrollStatus,
    {
        PayrollStatus.draft: '草稿',
        PayrollStatus.finalized: '已定稿',
        PayrollStatus.paid: '已发薪',
        PayrollStatus.voided: '已作废',
    },
)


class DetailSource(LabeledStrEnum):
    """薪资明细来源"""

    formula = 'formula'
    manual = 'manual'
    advance = 'advance'
    reversal = 'reversal'


_bind_labels(
    DetailSource,
    {
        DetailSource.formula: '公式',
        DetailSource.manual: '手工',
        DetailSource.advance: '预支抵扣',
        DetailSource.reversal: '反冲',
    },
)


class DayStatus(LabeledStrEnum):
    """日汇总状态"""

    has_data = 'has_data'
    no_orders = 'no_orders'
    not_imported = 'not_imported'
    no_plan = 'no_plan'


_bind_labels(
    DayStatus,
    {
        DayStatus.has_data: '有数据',
        DayStatus.no_orders: '无数据',
        DayStatus.not_imported: '未导入',
        DayStatus.no_plan: '无方案',
    },
)


class AdvanceStatus(LabeledStrEnum):
    """预支单状态"""

    draft = 'draft'
    pending = 'pending'
    rejected = 'rejected'
    to_pay = 'to_pay'
    paid = 'paid'
    cancelled = 'cancelled'


_bind_labels(
    AdvanceStatus,
    {
        AdvanceStatus.draft: '草稿',
        AdvanceStatus.pending: '待审核',
        AdvanceStatus.rejected: '已驳回',
        AdvanceStatus.to_pay: '待发放',
        AdvanceStatus.paid: '已发放',
        AdvanceStatus.cancelled: '已取消',
    },
)


class DeductStatus(LabeledStrEnum):
    """预支抵扣状态"""

    none = 'none'
    partial = 'partial'
    done = 'done'


_bind_labels(
    DeductStatus,
    {
        DeductStatus.none: '未抵扣',
        DeductStatus.partial: '部分抵扣',
        DeductStatus.done: '已抵扣',
    },
)


class TrialMode(LabeledStrEnum):
    """方案试算模式"""

    full_version = 'full_version'
    binding_segments = 'binding_segments'


_bind_labels(
    TrialMode,
    {
        TrialMode.full_version: '整版试算',
        TrialMode.binding_segments: '按绑定分段试算',
    },
)


class RecalcJobStatus(LabeledStrEnum):
    """重算任务状态（插件内轻量，非 Celery）"""

    queued = 'queued'
    running = 'running'
    done = 'done'
    failed = 'failed'


_bind_labels(
    RecalcJobStatus,
    {
        RecalcJobStatus.queued: '排队中',
        RecalcJobStatus.running: '计算中',
        RecalcJobStatus.done: '完成',
        RecalcJobStatus.failed: '失败',
    },
)


class RecalcJobSource(LabeledStrEnum):
    """重算任务来源"""

    import_batch = 'import_batch'
    stale_batch = 'stale_batch'
    period = 'period'


_bind_labels(
    RecalcJobSource,
    {
        RecalcJobSource.import_batch: '导入后重算',
        RecalcJobSource.stale_batch: '本站本月批量重算',
        RecalcJobSource.period: '单周期重算',
    },
)

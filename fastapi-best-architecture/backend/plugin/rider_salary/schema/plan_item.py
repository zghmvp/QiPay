from datetime import date, datetime
from typing import Any, Self

from pydantic import ConfigDict, Field, model_validator

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import CalcStage, TrialMode
from backend.plugin.rider_salary.schema.plan import GetPlanBrief
from backend.plugin.rider_salary.utils.item_summary import build_item_summary


class PlanItemParam(SchemaBase):
    """方案项写入"""

    subject_id: int = Field(description='科目 ID')
    name: str = Field(description='项名称')
    stage: CalcStage = Field(description='计算阶段')
    sort_order: int = Field(0, description='执行顺序')
    condition_json: dict[str, Any] | None = Field(None, description='触发条件')
    formula_json: dict[str, Any] | None = Field(None, description='计算公式')
    enabled: bool = Field(True, description='是否启用')
    remark: str | None = Field(None, description='备注')


class GetPlanItemDetail(SchemaBase):
    """方案项详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='方案项 ID')
    plan_version_id: int = Field(description='所属版本 ID')
    subject_id: int = Field(description='科目 ID')
    name: str = Field(description='项名称')
    stage: str = Field(description='计算阶段')
    sort_order: int = Field(description='执行顺序')
    condition_json: dict[str, Any] | None = Field(None, description='触发条件')
    formula_json: dict[str, Any] | None = Field(None, description='计算公式')
    condition_expr: str | None = Field(None, description='编译后条件')
    formula_expr: str | None = Field(None, description='编译后公式')
    enabled: bool = Field(description='是否启用')
    remark: str | None = Field(None, description='备注')
    summary: str = Field('', description='一句话说明（备注优先，否则条件+公式摘要）')

    @model_validator(mode='after')
    def _fill_summary(self) -> Self:
        object.__setattr__(
            self,
            'summary',
            build_item_summary(
                remark=self.remark,
                condition_expr=self.condition_expr,
                formula_expr=self.formula_expr,
                condition_json=self.condition_json,
                formula_json=self.formula_json,
            ),
        )
        return self


class GetPlanVersionDetail(SchemaBase):
    """方案版本详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='版本 ID')
    plan_id: int = Field(description='所属方案 ID')
    version_no: int = Field(description='版本号')
    status: str = Field(description='状态')
    mode_tag: str = Field(description='计薪模式标签')
    is_used: bool = Field(description='是否已被使用')
    items_hash: str | None = Field(None, description='方案项内容哈希')
    trial_hash: str | None = Field(None, description='试算内容哈希')
    trial_passed: bool = Field(description='试算通过')
    trial_snapshot: dict[str, Any] | None = Field(None, description='最近试算摘要')
    trial_mode: str | None = Field(
        None,
        description='最近试算模式：full_version 整版 / binding_segments 绑定感知',
    )
    binding_trial_passed: bool = Field(
        False,
        description='绑定感知试算已通过；启用吃这个，整版通过不等于按当前绑定出账',
    )
    copied_from_id: int | None = Field(None, description='复制来源版本 ID')
    activated_time: datetime | None = Field(None, description='启用时间')
    disabled_time: datetime | None = Field(None, description='停用时间')
    voided_time: datetime | None = Field(None, description='作废时间')
    remark: str | None = Field(None, description='备注')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')
    items: list[GetPlanItemDetail] = Field(default_factory=list, description='方案项')
    plan: GetPlanBrief | None = Field(None, description='所属方案')

    @model_validator(mode='after')
    def _fill_binding_trial_flags(self) -> Self:
        from backend.plugin.rider_salary.utils.plan_activate import ACTIVATION_TRIAL_MODE_KEY

        mode = None
        snap = self.trial_snapshot
        if isinstance(snap, dict):
            raw = snap.get(ACTIVATION_TRIAL_MODE_KEY)
            if raw:
                mode = str(raw)
        object.__setattr__(self, 'trial_mode', mode)
        object.__setattr__(
            self,
            'binding_trial_passed',
            bool(self.trial_passed) and mode == TrialMode.binding_segments.value,
        )
        return self


class TrialPlanVersionParam(SchemaBase):
    """试算参数"""

    rider_id: int = Field(description='骑手 ID')
    start_date: date = Field(description='开始日期')
    end_date: date = Field(description='结束日期')
    mode: TrialMode = Field(
        TrialMode.full_version,
        description='试算模式：整版试算（假定本版本全程生效）或按绑定分段试算',
    )

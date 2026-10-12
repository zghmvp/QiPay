from datetime import date, datetime
from typing import Annotated, Any, Self

from pydantic import ConfigDict, Field, model_validator

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import CalcStage
from backend.plugin.rider_salary.schema.limits import (
    LEN_NAME_64,
    LEN_REMARK,
    MAX_PLAN_ITEMS,
    MAX_SORT_ORDER,
    assert_formula_bounds,
    zh_list,
    zh_str,
)
from backend.plugin.rider_salary.schema.plan import GetPlanBrief


class PlanItemParam(SchemaBase):
    """方案项写入"""

    subject_id: int = Field(description='科目 ID')
    name: Annotated[str, zh_str('项名称', LEN_NAME_64, min_length=1)] = Field(
        min_length=1, max_length=LEN_NAME_64, description='项名称'
    )
    stage: CalcStage = Field(description='计算阶段')
    sort_order: int = Field(0, ge=0, le=MAX_SORT_ORDER, description='执行顺序')
    condition_json: dict[str, Any] | None = Field(None, description='触发条件')
    formula_json: dict[str, Any] | None = Field(None, description='计算公式')
    enabled: bool = Field(True, description='是否启用')
    remark: Annotated[str | None, zh_str('备注', LEN_REMARK)] = Field(None, max_length=LEN_REMARK, description='备注')

    @model_validator(mode='after')
    def check_formula_bounds(self) -> Self:
        """限制公式节点数和阶梯档数"""
        assert_formula_bounds(self.condition_json, self.formula_json)
        return self


PlanItemList = Annotated[
    list[PlanItemParam],
    zh_list('方案项', MAX_PLAN_ITEMS),
    Field(max_length=MAX_PLAN_ITEMS, description='方案项列表'),
]


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
    copied_from_id: int | None = Field(None, description='复制来源版本 ID')
    activated_time: datetime | None = Field(None, description='启用时间')
    disabled_time: datetime | None = Field(None, description='停用时间')
    voided_time: datetime | None = Field(None, description='作废时间')
    remark: str | None = Field(None, description='备注')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')
    items: list[GetPlanItemDetail] = Field(default_factory=list, description='方案项')
    plan: GetPlanBrief | None = Field(None, description='所属方案')


class TrialPlanVersionParam(SchemaBase):
    """试算参数"""

    rider_id: int = Field(description='骑手 ID')
    start_date: date = Field(description='开始日期')
    end_date: date = Field(description='结束日期')


class TrialUnsavedPlanParam(TrialPlanVersionParam):
    """未保存草稿试算参数。方案项只在内存中计算，不写入方案版本。"""

    items: Annotated[list[PlanItemParam], zh_list('方案项', MAX_PLAN_ITEMS)] = Field(description='方案项列表')

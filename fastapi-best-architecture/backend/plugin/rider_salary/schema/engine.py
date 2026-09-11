from typing import Any

from pydantic import Field

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import CalcStage


class EngineValidateParam(SchemaBase):
    """校验条件与公式"""

    stage: CalcStage = Field(description='计算阶段')
    condition_json: dict[str, Any] | None = Field(None, description='触发条件')
    formula_json: dict[str, Any] | None = Field(None, description='计算公式')


class EngineValidateResult(SchemaBase):
    """校验结果"""

    ok: bool = Field(description='是否通过')
    condition_expr: str = Field(description='编译后条件表达式')
    formula_expr: str = Field(description='编译后公式表达式')
    errors: list[str] = Field(default_factory=list, description='中文错误')


class EngineEvaluateParam(EngineValidateParam):
    """即时预览求值"""

    context: dict[str, Any] = Field(default_factory=dict, description='求值上下文')


class EngineEvaluateResult(SchemaBase):
    """预览求值结果"""

    hit: bool = Field(description='条件是否命中')
    amount: float = Field(description='金额')
    trace: dict[str, Any] = Field(default_factory=dict, description='计算过程')

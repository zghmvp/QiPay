from typing import Any, Self

from pydantic import Field, model_validator

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import CalcStage
from backend.plugin.rider_salary.schema.limits import assert_formula_bounds


class EngineValidateParam(SchemaBase):
    """校验条件与公式"""

    stage: CalcStage = Field(description='计算阶段')
    condition_json: dict[str, Any] | None = Field(None, description='触发条件')
    formula_json: dict[str, Any] | None = Field(None, description='计算公式')

    @model_validator(mode='after')
    def check_formula_bounds(self) -> Self:
        """限制公式节点数和阶梯档数"""
        assert_formula_bounds(self.condition_json, self.formula_json)
        return self


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

from decimal import Decimal
from typing import Any

from backend.plugin.rider_salary.engine.compiler import FORMULA_TEMPLATES, validate_item
from backend.plugin.rider_salary.engine.evaluator import evaluate_amount, evaluate_condition
from backend.plugin.rider_salary.engine.fields import fields_as_dicts, get_field
from backend.plugin.rider_salary.engine.functions import functions_as_dicts, to_minutes
from backend.plugin.rider_salary.engine.operators import operators_as_dicts, operators_for_field
from backend.plugin.rider_salary.schema.engine import (
    EngineEvaluateParam,
    EngineEvaluateResult,
    EngineValidateParam,
    EngineValidateResult,
)
from backend.plugin.rider_salary.utils.money import q2


class EngineService:
    """公式引擎元数据与校验"""

    @staticmethod
    def list_fields() -> list[dict]:
        """字段注册表"""
        return fields_as_dicts()

    @staticmethod
    def list_operators(field_name: str | None = None) -> dict[str, Any]:
        """按类型或字段返回运算符"""
        if field_name:
            spec = get_field(field_name)
            return {
                'field': field_name,
                'type': spec.type if spec else None,
                'operators': operators_for_field(field_name),
            }
        return operators_as_dicts()

    @staticmethod
    def list_functions() -> list[dict[str, Any]]:
        """函数签名"""
        return functions_as_dicts()

    @staticmethod
    def list_templates() -> list[dict[str, Any]]:
        """公式模板骨架"""
        return [dict(item) for item in FORMULA_TEMPLATES]

    @staticmethod
    def validate(obj: EngineValidateParam) -> EngineValidateResult:
        """校验并编译"""
        result = validate_item(obj.stage, obj.condition_json, obj.formula_json)
        return EngineValidateResult(
            ok=result.ok,
            condition_expr=result.condition_expr,
            formula_expr=result.formula_expr,
            errors=result.errors,
        )

    @staticmethod
    def evaluate_sample(obj: EngineEvaluateParam) -> EngineEvaluateResult:
        """给定上下文即时求值"""
        compiled = validate_item(obj.stage, obj.condition_json, obj.formula_json)
        context = dict(obj.context or {})
        for key, value in list(context.items()):
            spec = get_field(key)
            if spec is not None and spec.type == 'time':
                context[key] = to_minutes(value)
        if not compiled.ok:
            return EngineEvaluateResult(
                hit=False,
                amount=0,
                trace={'错误': compiled.errors, '条件': compiled.condition_expr, '公式': compiled.formula_expr},
            )
        hit = evaluate_condition(compiled.condition_expr, context)
        amount = q2(Decimal(0))
        if hit:
            amount = evaluate_amount(compiled.formula_expr, context)
        from backend.plugin.rider_salary.engine.context import trace_variables

        return EngineEvaluateResult(
            hit=hit,
            amount=float(amount),
            trace={
                '条件': compiled.condition_expr,
                '条件结果': hit,
                '公式': compiled.formula_expr,
                '变量': trace_variables(f'{compiled.condition_expr} {compiled.formula_expr}', context),
                '结果': float(amount),
            },
        )


engine_service = EngineService()

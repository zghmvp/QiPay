from decimal import Decimal
from typing import Any

from backend.common.exception import errors
from backend.plugin.rider_salary.engine.compiler import FORMULA_TEMPLATES, validate_item
from backend.plugin.rider_salary.engine.context import trace_variables
from backend.plugin.rider_salary.engine.evaluator import EvalError, evaluate_amount, evaluate_condition
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
        """给定上下文即时求值。运行期失败返回中文 400，不按 0 元处理。"""
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
        try:
            hit = evaluate_condition(compiled.condition_expr, context)
        except EvalError as exc:
            raise errors.RequestError(msg=_sample_eval_error('条件', exc, obj.formula_json)) from exc
        amount = q2(Decimal(0))
        if hit:
            try:
                amount = evaluate_amount(compiled.formula_expr, context)
            except EvalError as exc:
                raise errors.RequestError(msg=_sample_eval_error('公式', exc, obj.formula_json)) from exc
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


def _formula_item_name(formula_json: dict[str, Any] | None) -> str | None:
    if not isinstance(formula_json, dict):
        return None
    raw = formula_json.get('名称')
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _zh_eval_reason(exc: EvalError) -> str:
    """把求值异常收成中文原因。除零等文案本身已是中文。"""
    text = str(exc).strip() or '未知错误'
    if ' is not defined' in text:
        start = text.find("'")
        end = text.find("'", start + 1)
        if 0 <= start < end:
            return f'变量「{text[start + 1 : end]}」未提供'
        return '引用了未提供的变量'
    return text


def _sample_eval_error(part: str, exc: EvalError, formula_json: dict[str, Any] | None) -> str:
    reason = _zh_eval_reason(exc)
    name = _formula_item_name(formula_json)
    if name:
        return f'计薪项「{name}」{part}求值失败：{reason}'
    return f'{part}求值失败：{reason}'


engine_service = EngineService()

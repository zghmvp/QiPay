"""方案项一句话说明：备注优先，否则条件+公式摘要（供管理端/骑手端只读展示）。"""

from __future__ import annotations

from typing import Any


def _formula_from_json(formula_json: dict[str, Any] | None) -> str | None:
    if not formula_json:
        return None
    kind = formula_json.get('类型')
    if kind == '固定金额':
        return f'固定金额 {formula_json.get("金额", "")}'
    if kind == '字段乘单价':
        return f'({formula_json.get("字段", "")} − {formula_json.get("起算值", 0)}) × {formula_json.get("单价", "")}'
    if kind == '阶梯':
        return f'阶梯 {formula_json.get("字段", "")} / {formula_json.get("模式", "")} / {formula_json.get("计价", "")}'
    if kind == '表达式':
        return str(formula_json.get('表达式') or '表达式')
    if formula_json.get('表达式'):
        return str(formula_json['表达式'])
    if '金额' in formula_json:
        return f'固定金额 {formula_json.get("金额", "")}'
    return None


def _condition_from_json(condition_json: dict[str, Any] | None) -> str | None:
    if not condition_json:
        return None
    nodes = condition_json.get('条件')
    if not isinstance(nodes, list) or not nodes:
        return None
    logic = condition_json.get('逻辑') or '且'
    parts: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if '条件' in node:
            parts.append('…')
            continue
        field = node.get('字段') or ''
        op = node.get('运算符') or ''
        value = node.get('值')
        if isinstance(value, list):
            value_text = '~'.join(str(v) for v in value)
        elif isinstance(value, bool):
            value_text = '是' if value else '否'
        elif value is None:
            value_text = ''
        else:
            value_text = str(value)
        parts.append(f'{field} {op} {value_text}'.strip())
    text = f' {logic} '.join(p for p in parts if p)
    return text or None


def build_item_summary(
    *,
    remark: str | None = None,
    condition_expr: str | None = None,
    formula_expr: str | None = None,
    condition_json: dict[str, Any] | None = None,
    formula_json: dict[str, Any] | None = None,
) -> str:
    """生成方案项一句话说明（不展示原始 JSON）。"""
    if remark and remark.strip():
        return remark.strip()

    cond = (condition_expr or '').strip()
    if not cond or cond == 'True':
        cond = _condition_from_json(condition_json) or ''
        if not cond:
            cond = ''
    if cond in {'True', '恒真（空条件）'}:
        cond = ''

    formula = (formula_expr or '').strip()
    if not formula:
        formula = _formula_from_json(formula_json) or ''

    parts: list[str] = []
    if cond:
        parts.append(f'条件 {cond}')
    if formula:
        parts.append(formula)
    return '；'.join(parts) if parts else '—'

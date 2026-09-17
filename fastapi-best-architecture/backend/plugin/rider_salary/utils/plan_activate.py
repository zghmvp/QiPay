"""启用闸门：整版试算通过 ≠ 按当前绑定出账。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import CalcStage, TrialMode

if TYPE_CHECKING:
    from datetime import date

ACTIVATION_TRIAL_MODE_KEY = 'activation_trial_mode'
FULL_TRIAL_NOT_PAYROLL_MSG = '整版试算通过不等于按当前绑定出账，请先完成绑定感知试算再启用'
PARTIAL_SEGMENT_FIXED_AMOUNT_MSG = '非整周期绑定下，周期固定金额本段将按全额计一次，不是分摊'
NO_TRIAL_MSG = '请先完成试算再启用'
TRIAL_HASH_CHANGED_MSG = '方案内容已变更，请重新试算'


def _stage_value(raw: Any) -> str:
    if raw is None:
        return ''
    if hasattr(raw, 'value'):
        return str(raw.value)
    return str(raw)


def _item_as_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, 'model_dump'):
        return item.model_dump()
    return {
        'name': getattr(item, 'name', '') or '',
        'stage': getattr(item, 'stage', None),
        'enabled': getattr(item, 'enabled', True),
        'formula_json': getattr(item, 'formula_json', None),
    }


def activation_trial_mode(version: Any) -> str | None:
    """最近一次试算写入启用闸门的模式。缺省视为整版（旧数据 fail-closed）。"""
    snap = getattr(version, 'trial_snapshot', None)
    if isinstance(snap, dict):
        raw = snap.get(ACTIVATION_TRIAL_MODE_KEY)
        if raw:
            return str(raw)
    return None


def binding_trial_passed(version: Any) -> bool:
    """绑定感知试算已盖章且 trial_passed。"""
    return bool(getattr(version, 'trial_passed', False)) and (
        activation_trial_mode(version) == TrialMode.binding_segments.value
    )


def _trial_mode_value(mode: TrialMode | str) -> str:
    """SchemaBase use_enum_values=True 时接口传入的是 str，不是 Enum。"""
    if isinstance(mode, TrialMode):
        return mode.value
    return str(getattr(mode, 'value', mode))


def stamp_trial_for_activate(
    version: Any,
    *,
    mode: TrialMode | str,
    current_hash: str,
    summary: dict[str, Any],
) -> None:
    """整版与绑定感知都写 trial_passed；启用只认 binding_segments。"""
    snapshot = dict(summary)
    snapshot[ACTIVATION_TRIAL_MODE_KEY] = _trial_mode_value(mode)
    version.items_hash = current_hash
    version.trial_hash = current_hash
    version.trial_passed = True
    version.trial_snapshot = snapshot


def clear_activation_trial_stamp(version: Any) -> None:
    """方案项变更后清掉启用闸门。"""
    version.trial_passed = False
    snap = getattr(version, 'trial_snapshot', None)
    if isinstance(snap, dict) and ACTIVATION_TRIAL_MODE_KEY in snap:
        cleaned = {key: value for key, value in snap.items() if key != ACTIVATION_TRIAL_MODE_KEY}
        version.trial_snapshot = cleaned or None


def assert_activate_trial_is_binding_aware(version: Any, current_hash: str) -> None:
    """启用必须吃绑定感知试算，禁止把整版 what-if 当出账承诺。"""
    if not getattr(version, 'trial_passed', False):
        raise errors.RequestError(msg=NO_TRIAL_MSG)
    if getattr(version, 'trial_hash', None) != current_hash:
        raise errors.RequestError(msg=TRIAL_HASH_CHANGED_MSG)
    if activation_trial_mode(version) != TrialMode.binding_segments.value:
        raise errors.RequestError(msg=FULL_TRIAL_NOT_PAYROLL_MSG)


def has_fixed_period_amount(items: list[Any] | None) -> bool:
    """周期阶段「固定金额」项（跨段各计一次全额）。"""
    for item in items or []:
        data = _item_as_dict(item)
        if not bool(data.get('enabled', True)):
            continue
        if _stage_value(data.get('stage')) != CalcStage.period.value:
            continue
        formula = data.get('formula_json')
        if isinstance(formula, dict) and formula.get('类型') == '固定金额':
            return True
    return False


def is_partial_binding_range(
    start: date,
    end: date,
    segments: list[Any] | None,
) -> bool:
    """绑定段不是整段试算窗（多段或任一段短于窗）。"""
    if not segments:
        return False
    span = (end - start).days + 1
    if len(list(segments)) >= 2:
        return True
    for seg in segments:
        seg_start = getattr(seg, 'start_date', start)
        seg_end = getattr(seg, 'end_date', end)
        if (seg_end - seg_start).days + 1 < span:
            return True
    return False


def partial_segment_fixed_amount_warning(
    items: list[Any] | None,
    start: date,
    end: date,
    segments: list[Any] | None,
) -> str | None:
    """非整周期绑定 + 周期固定额：中文说明本段按全额计一次。"""
    if has_fixed_period_amount(items) and is_partial_binding_range(start, end, segments):
        return PARTIAL_SEGMENT_FIXED_AMOUNT_MSG
    return None

"""P0-18 保底项排序校验。

Q-13 未拍板，按推荐方案：保存和启用时拒绝，不自动改顺序。
P1-03 集成基座尚未就绪（没有 tests/integration/），验收写在服务层单测。
"""

import json
import re

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anyio
import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.engine.compiler import references_accrued_amount
from backend.plugin.rider_salary.enums import PlanVersionStatus
from backend.plugin.rider_salary.schema.plan_item import PlanItemParam
from backend.plugin.rider_salary.service import plan_service as plan_mod
from backend.plugin.rider_salary.service.plan_service import (
    PlanService,
    assert_accrued_items_last,
    items_hash_of,
    orm_items_as_dicts,
    plan_service,
)

GUARANTEE = {'类型': '表达式', '表达式': '最大值(0, 3500 - 本期已计金额)'}
FIXED = {'类型': '固定金额', '金额': 10}
REPO_ROOT = Path(__file__).resolve().parents[5]
PRESET_PATH = (
    REPO_ROOT / 'fastapi-best-architecture-ui/apps/web-antdv-next/src/plugins/rider-salary/constants/plan-presets.ts'
)
CATALOG_PATH = PRESET_PATH.with_name('plan-presets.json')
CASE_LIBRARY_PATH = REPO_ROOT / 'docs/设计/04-薪资方案案例库.md'
STAGE_ORDER = ('per_order', 'daily', 'period')


def _item(
    name: str,
    stage: str,
    sort_order: int,
    formula: dict | None = None,
    *,
    enabled: bool = True,
    condition: dict | None = None,
    formula_expr: str | None = None,
    condition_expr: str | None = None,
) -> dict:
    return {
        'name': name,
        'stage': stage,
        'sort_order': sort_order,
        'enabled': enabled,
        'condition_json': condition or {},
        'formula_json': formula or FIXED,
        'condition_expr': condition_expr,
        'formula_expr': formula_expr,
    }


def _param(item: dict) -> PlanItemParam:
    return PlanItemParam(
        subject_id=1,
        name=item['name'],
        stage=item['stage'],
        sort_order=item['sort_order'],
        condition_json=item['condition_json'],
        formula_json=item['formula_json'],
        enabled=item['enabled'],
    )


def _misordered() -> list[dict]:
    """保底项排在全勤奖之前。"""
    return [
        _item('提成', 'per_order', 10, {'类型': '固定金额', '金额': 3.5}),
        _item('保底补足', 'period', 10, GUARANTEE),
        _item('全勤奖', 'period', 20),
    ]


def _c05() -> list[dict]:
    return [
        _item('提成', 'per_order', 10, {'类型': '固定金额', '金额': 3.5}),
        _item('保底补足', 'period', 90, GUARANTEE),
    ]


def _draft(**kwargs: object) -> SimpleNamespace:
    data: dict[str, object] = {
        'is_used': False,
        'status': PlanVersionStatus.draft.value,
        'items_hash': None,
        'trial_passed': False,
        'trial_hash': None,
        'plan_id': 1,
        'version_no': 1,
        'activated_time': None,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def test_references_accrued_from_formula_condition_and_compiled_expr() -> None:
    assert references_accrued_amount(formula_json=GUARANTEE) is True
    assert references_accrued_amount(formula_json=FIXED) is False
    assert references_accrued_amount(formula_json={'类型': '字段乘单价', '字段': '本期已计金额', '单价': 1}) is True
    assert references_accrued_amount(formula_json={'类型': '阶梯', '字段': '本期已计金额', '档位': []}) is True
    condition = {'逻辑': '且', '条件': [{'字段': '本期已计金额', '运算符': '>', '值': 0}]}
    assert references_accrued_amount(condition_json=condition) is True
    assert references_accrued_amount(formula_expr='最大值(0, 3500 - 本期已计金额)') is True
    assert references_accrued_amount(formula_json={'类型': '表达式', '表达式': '周期有效单量 * 5'}) is False


def test_guarantee_before_period_item_is_rejected() -> None:
    with pytest.raises(errors.RequestError, match='保底项「保底补足」引用「本期已计金额」') as caught:
        assert_accrued_items_last(_misordered())
    assert caught.value.code == 400


def test_guarantee_last_among_period_items_passes() -> None:
    assert_accrued_items_last(_c05())
    assert_accrued_items_last([
        _item('全勤奖', 'period', 10),
        _item('保底补足', 'period', 20, GUARANTEE),
        _item('基础单价', 'per_order', 100),
    ])


def test_tied_sort_order_is_rejected() -> None:
    with pytest.raises(errors.RequestError, match='保底补足'):
        assert_accrued_items_last([
            _item('全勤奖', 'period', 20),
            _item('保底补足', 'period', 20, GUARANTEE),
        ])


def test_condition_reference_must_also_be_last() -> None:
    condition = {'逻辑': '且', '条件': [{'字段': '本期已计金额', '运算符': '>', '值': 1000}]}
    with pytest.raises(errors.RequestError, match='门槛'):
        assert_accrued_items_last([
            _item('门槛', 'period', 10, condition=condition),
            _item('全勤奖', 'period', 20),
        ])


def test_compiled_expr_reference_without_json_is_rejected() -> None:
    with pytest.raises(errors.RequestError, match='保底补足'):
        assert_accrued_items_last([
            _item('保底补足', 'period', 10, formula_expr='最大值(0, 3000 - 本期已计金额)'),
            _item('全勤奖', 'period', 20),
        ])


def test_disabled_guarantee_does_not_block() -> None:
    assert_accrued_items_last([
        _item('保底补足', 'period', 10, GUARANTEE, enabled=False),
        _item('全勤奖', 'period', 20),
    ])


def test_disabled_later_item_does_not_block_guarantee() -> None:
    assert_accrued_items_last([
        _item('保底补足', 'period', 10, GUARANTEE),
        _item('全勤奖', 'period', 90, enabled=False),
    ])


def test_non_period_reference_is_not_a_sort_error() -> None:
    assert_accrued_items_last([
        _item('错阶段', 'per_order', 1, formula_expr='本期已计金额'),
    ])


def test_two_accrued_items_only_the_earlier_one_fails() -> None:
    with pytest.raises(errors.RequestError, match='保底甲') as caught:
        assert_accrued_items_last([
            _item('保底甲', 'period', 10, GUARANTEE),
            _item('保底乙', 'period', 20, GUARANTEE),
        ])
    assert '保底乙' not in (caught.value.msg or '')


def test_replace_items_returns_400_and_does_not_write() -> None:
    version = _draft()

    async def _case() -> None:
        with (
            patch.object(PlanService, 'get_version_model', new=AsyncMock(return_value=version)),
            patch.object(
                plan_mod.plan_item_dao,
                'logical_delete_by_version',
                new=AsyncMock(side_effect=AssertionError('排序不合法时不应写库')),
            ),
        ):
            with pytest.raises(errors.RequestError, match='保底补足') as caught:
                await plan_service.replace_items(
                    AsyncMock(),
                    1,
                    [_param(item) for item in _misordered()],
                    SimpleNamespace(),
                )
        assert caught.value.code == 400

    anyio.run(_case)


def test_replace_items_accepts_guarantee_last() -> None:
    version = _draft(items_hash='old')
    detail = SimpleNamespace(id=1)

    async def _case() -> None:
        with (
            patch.object(PlanService, 'get_version_model', new=AsyncMock(return_value=version)),
            patch.object(plan_mod.plan_item_dao, 'list_by_version', new=AsyncMock(return_value=[])),
            patch.object(plan_mod.plan_item_dao, 'logical_delete_by_version', new=AsyncMock()) as deleted,
            patch.object(plan_mod.plan_item_dao, 'create', new=AsyncMock()) as created,
            patch.object(plan_mod, 'assert_plan_item_subjects', new=AsyncMock()),
            patch.object(plan_mod.audit_service, 'record', new=AsyncMock()),
            patch.object(PlanService, 'get_version', new=AsyncMock(return_value=detail)),
        ):
            result = await plan_service.replace_items(
                AsyncMock(),
                7,
                [_param(item) for item in _c05()],
                SimpleNamespace(),
            )
        assert result is detail
        deleted.assert_awaited_once()
        assert created.await_count == 2
        assert version.trial_passed is False

    anyio.run(_case)


def test_activate_rejects_misordered_draft() -> None:
    version = _draft(trial_passed=True, trial_hash='matched', items_hash='matched')
    rows = [SimpleNamespace(**item, subject_id=1) for item in _misordered()]

    async def _case() -> None:
        with (
            patch.object(PlanService, 'get_version_model', new=AsyncMock(return_value=version)),
            patch.object(plan_mod.plan_item_dao, 'list_by_version', new=AsyncMock(return_value=rows)),
            patch.object(plan_mod.plan_dao, 'get', new=AsyncMock(side_effect=AssertionError('不应启用'))),
        ):
            with pytest.raises(errors.RequestError, match='保底补足') as caught:
                await plan_service.activate(AsyncMock(), 1, SimpleNamespace())
        assert caught.value.code == 400
        assert version.status == PlanVersionStatus.draft.value

    anyio.run(_case)


def test_activate_accepts_guarantee_last() -> None:
    rows = [SimpleNamespace(**item, subject_id=1) for item in _c05()]
    digest = items_hash_of(orm_items_as_dicts(rows))
    version = _draft(trial_passed=True, trial_hash=digest, items_hash=digest)

    async def _case() -> None:
        with (
            patch.object(PlanService, 'get_version_model', new=AsyncMock(return_value=version)),
            patch.object(plan_mod.plan_item_dao, 'list_by_version', new=AsyncMock(return_value=rows)),
            patch.object(plan_mod, 'assert_plan_item_subjects', new=AsyncMock()),
            patch.object(plan_mod.plan_dao, 'get', new=AsyncMock(return_value=SimpleNamespace(name='保底'))),
            patch.object(plan_mod.audit_service, 'record', new=AsyncMock()) as audit,
        ):
            await plan_service.activate(AsyncMock(), 3, SimpleNamespace())
        assert version.status == PlanVersionStatus.active.value
        audit.assert_awaited_once()

    anyio.run(_case)


def test_activate_already_active_version_skips_sort_check() -> None:
    """已启用历史版本不可变，再次调用启用不因旧顺序被拒。"""
    version = _draft(status=PlanVersionStatus.active.value, trial_passed=False)
    rows = [SimpleNamespace(**item, subject_id=1) for item in _misordered()]

    async def _case() -> None:
        with (
            patch.object(PlanService, 'get_version_model', new=AsyncMock(return_value=version)),
            patch.object(plan_mod.plan_item_dao, 'list_by_version', new=AsyncMock(return_value=rows)),
        ):
            with pytest.raises(errors.RequestError, match='请先完成试算再启用'):
                await plan_service.activate(AsyncMock(), 1, SimpleNamespace())

    anyio.run(_case)


def _take_delimited(text: str, start: int, open_char: str, close_char: str) -> tuple[str, int]:
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return text[start : index + 1], index + 1
    raise AssertionError('括号不匹配')


def _preset_items(text: str) -> list[tuple[str, list[tuple[str, bool]]]]:
    found: list[tuple[str, list[tuple[str, bool]]]] = []
    for match in re.finditer(r"\bid:\s*'([^']+)'", text):
        rest = text[match.end() :]
        next_id = re.search(r"\bid:\s*'[^']+'", rest)
        body = rest[: next_id.start()] if next_id else rest
        items_at = body.find('items:')
        if items_at < 0:
            found.append((match.group(1), []))
            continue
        bracket = body.find('[', items_at)
        array_text, _end = _take_delimited(body, bracket, '[', ']')
        found.append((match.group(1), _item_flags(array_text)))
    return found


def _item_flags(array_text: str) -> list[tuple[str, bool]]:
    flags: list[tuple[str, bool]] = []
    inner = array_text[1:-1]
    cursor = 0
    while True:
        brace = inner.find('{', cursor)
        if brace < 0:
            break
        obj, cursor = _take_delimited(inner, brace, '{', '}')
        stage_match = re.search(r"stage:\s*'(per_order|daily|period)'", obj)
        if stage_match is None:
            continue
        references = bool(
            re.search(r"表达式:\s*(?:`[^`]*本期已计金额[^`]*`|'[^']*本期已计金额[^']*')", obj)
            or re.search(r"字段:\s*'本期已计金额'", obj)
        )
        flags.append((stage_match.group(1), references))
    return flags


def _preset_payload(flags: list[tuple[str, bool]]) -> list[dict]:
    ordered = [item for stage in STAGE_ORDER for item in flags if item[0] == stage]
    payload: list[dict] = []
    for index, (stage, references) in enumerate(ordered):
        formula = GUARANTEE if references else FIXED
        payload.append(_item(f'项{index}', stage, index, formula))
    return payload


def _preset_items_from_catalog(text: str) -> list[tuple[str, list[tuple[str, bool]]]]:
    catalog = json.loads(text)
    found: list[tuple[str, list[tuple[str, bool]]]] = []
    for preset in catalog['presets']:
        flags: list[tuple[str, bool]] = []
        for item in preset['items']:
            blob = json.dumps(
                {'formula': item.get('formula_json') or {}, 'condition': item.get('condition_json') or {}},
                ensure_ascii=False,
            )
            flags.append((item['stage'], '本期已计金额' in blob))
        found.append((preset['id'], flags))
    return found


def test_plan_presets_can_be_saved_and_enabled() -> None:
    if CATALOG_PATH.is_file():
        presets = _preset_items_from_catalog(CATALOG_PATH.read_text(encoding='utf-8'))
    else:
        presets = _preset_items(PRESET_PATH.read_text(encoding='utf-8'))
    assert presets, '未解析到内置案例'
    referenced = [preset_id for preset_id, items in presets if any(stage == 'period' and ref for stage, ref in items)]
    assert referenced == ['C05']
    for preset_id, items in presets:
        assert_accrued_items_last(_preset_payload(items))
        assert preset_id


def _case_tables(text: str) -> list[list[tuple[int, str, bool]]]:
    tables: list[list[tuple[int, str, bool]]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith('|'):
            current.append(line)
            continue
        if current:
            parsed = _parse_case_table(current)
            if parsed:
                tables.append(parsed)
            current = []
    if current:
        parsed = _parse_case_table(current)
        if parsed:
            tables.append(parsed)
    return tables


def _parse_case_table(lines: list[str]) -> list[tuple[int, str, bool]]:
    rows = [[cell.strip() for cell in line.strip().strip('|').split('|')] for line in lines]
    if not rows or rows[0][0] != 'sort' or 'stage' not in rows[0]:
        return []
    stage_at = rows[0].index('stage')
    parsed: list[tuple[int, str, bool]] = []
    for cells in rows[1:]:
        if not cells or not cells[0].isdigit() or len(cells) <= stage_at:
            continue
        parsed.append((int(cells[0]), cells[stage_at], '本期已计金额' in ' '.join(cells)))
    return parsed


def test_case_library_accrued_items_stay_last() -> None:
    tables = _case_tables(CASE_LIBRARY_PATH.read_text(encoding='utf-8'))
    assert tables, '案例库没有可解析的方案表'
    referenced = 0
    for table in tables:
        period = [row for row in table if row[1] == 'period']
        if not period:
            continue
        max_sort = max(row[0] for row in period)
        for sort_order, _stage, references in period:
            if not references:
                continue
            referenced += 1
            assert sort_order == max_sort
            assert not any(other[0] >= sort_order and not other[2] for other in period)
        payload = [
            _item(
                f'项{sort_order}',
                stage,
                sort_order,
                GUARANTEE if references else FIXED,
            )
            for sort_order, stage, references in table
        ]
        assert_accrued_items_last(payload)
    assert referenced == 1

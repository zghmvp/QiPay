"""P2-02：科目计算语义。缺失科目不再按奖励、进应发兜底。

Q-10 采用推荐方案 A，不在方案项上快照方向和是否进应发。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.engine.segments import load_plan_item_views
from backend.plugin.rider_salary.schema.subject import UpdateSubjectParam
from backend.plugin.rider_salary.service.plan_service import plan_item_subject_error
from backend.plugin.rider_salary.service.subject_service import calc_semantics_changed


def _item() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        subject_id=9,
        name='夜间补贴',
        stage='per_order',
        sort_order=0,
        condition_json=None,
        formula_json=None,
        condition_expr='True',
        formula_expr='2',
        enabled=True,
    )


def _scalars(rows: list[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


def test_missing_subject_does_not_fall_back_to_bonus() -> None:
    """科目被删掉时算薪读方案项直接报错，不再当成奖励且进应发。"""

    async def _case() -> None:
        db = AsyncMock()
        db.scalars = AsyncMock(side_effect=[_scalars([_item()]), _scalars([])])
        with pytest.raises(errors.RequestError, match='科目不存在') as caught:
            await load_plan_item_views(db, 1)
        assert caught.value.code == 400

    anyio.run(_case)


def test_loaded_subject_keeps_penalty_and_gross_flag() -> None:
    """科目还在时，方向和是否进应发用科目上的值。"""
    subject = SimpleNamespace(id=9, direction='penalty', include_in_gross=False)

    async def _case() -> None:
        db = AsyncMock()
        db.scalars = AsyncMock(side_effect=[_scalars([_item()]), _scalars([subject])])
        views = await load_plan_item_views(db, 1)
        assert views[0].direction == 'penalty'
        assert views[0].include_in_gross is False

    anyio.run(_case)


def test_plan_item_subject_must_exist_be_enabled_and_unscoped() -> None:
    """保存前：不存在、已停用、限定了站点或用工类型，都要拒绝。"""
    enabled = SimpleNamespace(status='enable', scope_sites=None, scope_employ_types=[])
    assert plan_item_subject_error(enabled, index=1, name='基础单价') is None
    assert '科目不存在' in (plan_item_subject_error(None, index=2, name='底薪') or '')
    disabled = SimpleNamespace(status='disable', scope_sites=None, scope_employ_types=None)
    assert '已停用' in (plan_item_subject_error(disabled, index=1, name='超时') or '')
    scoped = SimpleNamespace(status='enable', scope_sites=[3], scope_employ_types=None)
    assert '适用范围' in (plan_item_subject_error(scoped, index=1, name='站点奖') or '')
    employ = SimpleNamespace(status='enable', scope_sites=[], scope_employ_types=['full_time'])
    assert '适用范围' in (plan_item_subject_error(employ, index=1, name='全职奖') or '')


def test_semantics_change_ignores_omitted_fields() -> None:
    """只改名称不算改计算语义；方向和是否进应发与原值相同也不算。"""
    before = SimpleNamespace(direction='bonus', include_in_gross=True)
    assert not calc_semantics_changed(before, UpdateSubjectParam(name='新名称'))
    assert calc_semantics_changed(before, UpdateSubjectParam(direction='penalty'))
    assert calc_semantics_changed(before, UpdateSubjectParam(include_in_gross=False))
    assert not calc_semantics_changed(before, UpdateSubjectParam(direction='bonus', include_in_gross=True))

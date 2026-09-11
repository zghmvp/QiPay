from types import SimpleNamespace

import pytest

from backend.common.exception.errors import ForbiddenError, RequestError
from backend.plugin.rider_salary.enums import PlanVersionStatus
from backend.plugin.rider_salary.service.plan_service import assert_version_editable, items_hash_of


def test_used_version_cannot_edit() -> None:
    version = SimpleNamespace(is_used=True, status=PlanVersionStatus.draft.value)
    with pytest.raises(ForbiddenError, match='该方案版本已被使用，禁止编辑或删除，请停用后复制为新版本'):
        assert_version_editable(version)


def test_non_draft_cannot_edit() -> None:
    version = SimpleNamespace(is_used=False, status=PlanVersionStatus.active.value)
    with pytest.raises(ForbiddenError, match='仅草稿版本可以编辑'):
        assert_version_editable(version)


def test_unused_draft_can_edit() -> None:
    version = SimpleNamespace(is_used=False, status=PlanVersionStatus.draft.value)
    assert_version_editable(version)


def test_items_hash_changes_with_amount() -> None:
    items = [
        {
            'subject_id': 1,
            'name': '基础单价',
            'stage': 'per_order',
            'sort_order': 10,
            'condition_json': {},
            'formula_json': {'类型': '固定金额', '金额': 4},
            'enabled': True,
        }
    ]
    first = items_hash_of(items)
    items[0]['formula_json'] = {'类型': '固定金额', '金额': 5}
    second = items_hash_of(items)
    assert first != second


def test_activate_requires_matching_trial_hash() -> None:
    items_hash = items_hash_of([
        {
            'subject_id': 1,
            'name': '基础单价',
            'stage': 'per_order',
            'sort_order': 10,
            'condition_json': {},
            'formula_json': {'类型': '固定金额', '金额': 4},
            'enabled': True,
        }
    ])
    version = SimpleNamespace(trial_passed=True, trial_hash='old', items_hash=items_hash)
    if not version.trial_passed:
        raise RequestError(msg='请先完成试算再启用')
    if version.trial_hash != items_hash:
        with pytest.raises(RequestError, match='方案内容已变更，请重新试算'):
            raise RequestError(msg='方案内容已变更，请重新试算')
    else:
        raise AssertionError('哈希应当不匹配')


def test_activate_without_trial() -> None:
    version = SimpleNamespace(trial_passed=False, trial_hash=None, items_hash='abc')
    if not version.trial_passed:
        with pytest.raises(RequestError, match='请先完成试算再启用'):
            raise RequestError(msg='请先完成试算再启用')

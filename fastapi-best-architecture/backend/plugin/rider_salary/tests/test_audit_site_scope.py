"""审计站点范围：写入打 site_id，列表按可见站过滤，NULL 对负责人失败封闭。"""

import inspect

import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.tests.rbac_support import PLUGIN_ROOT
from backend.plugin.rider_salary.utils.audit import (
    SITE_SCOPED_TARGET_TYPES,
    AuditService,
    require_audit_site_id,
)


def test_require_audit_site_id_site_scoped_rejects_none() -> None:
    for target in ('order', 'rider', 'period', 'payroll', 'import_batch', 'binding'):
        with pytest.raises(errors.RequestError) as exc:
            require_audit_site_id(target, None)
        assert exc.value.msg == '站点型操作必须写入所属站点'
        require_audit_site_id(target, 7)


def test_require_audit_site_id_global_allows_none() -> None:
    require_audit_site_id('subject', None)
    require_audit_site_id('plan', None)
    require_audit_site_id('plan_version', None)
    require_audit_site_id('notice', None)


def test_record_requires_explicit_site_id_keyword() -> None:
    param = inspect.signature(AuditService.record).parameters['site_id']
    assert param.default is inspect.Parameter.empty
    assert param.kind is inspect.Parameter.KEYWORD_ONLY


def test_site_scoped_types_cover_council_objects() -> None:
    expected = {
        'site',
        'rider',
        'rider_employ_history',
        'rider_plan_binding',
        'binding',
        'order',
        'import_batch',
        'adjustment',
        'day_flag',
        'advance',
        'period',
        'payroll',
    }
    assert expected <= SITE_SCOPED_TARGET_TYPES


def test_patch_adds_and_backfills_site_id() -> None:
    patch = (PLUGIN_ROOT / 'sql' / 'patch' / '007_audit_log_site_id.sql').read_text(encoding='utf-8')
    assert 'add column if not exists site_id' in patch
    assert 'where site_id is null' in patch
    assert '生成周期' in patch
    assert 'ilike' not in patch.lower()
    assert '权限站' not in patch


def test_callers_pass_site_id() -> None:
    service_dir = PLUGIN_ROOT / 'service'
    missing: list[str] = []
    for path in sorted(service_dir.glob('*.py')):
        text = path.read_text(encoding='utf-8')
        if 'audit_service.record(' not in text:
            continue
        idx = 0
        while True:
            start = text.find('audit_service.record(', idx)
            if start < 0:
                break
            block = text[start : start + 900]
            if 'site_id=' not in block:
                missing.append(f'{path.name}:{text.count(chr(10), 0, start) + 1}')
            idx = start + 8
    assert missing == []


def test_model_has_nullable_site_id() -> None:
    text = (PLUGIN_ROOT / 'model' / 'audit_log.py').read_text(encoding='utf-8')
    assert 'site_id' in text
    assert '所属站点；空表示全局目录或无法归属' in text
    assert 'default=None' in text

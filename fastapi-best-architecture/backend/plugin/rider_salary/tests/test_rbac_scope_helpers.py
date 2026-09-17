"""无库：visible None vs 空集，以及列表哨兵。"""

import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.tests.rbac_support import PLUGIN_ROOT
from backend.plugin.rider_salary.utils.deps import assert_site_visible


def test_visible_none_vs_empty() -> None:
    assert_site_visible(None, 1)
    assert_site_visible(None, 99)
    with pytest.raises(errors.ForbiddenError) as exc:
        assert_site_visible(set(), 1)
    assert exc.value.msg == '无权访问该站点数据'
    with pytest.raises(errors.ForbiddenError):
        assert_site_visible({2, 3}, 1)
    assert_site_visible({1, 2}, 1)


def test_empty_visible_crud_sentinels() -> None:
    """空集合必须变成查不到行的哨兵；payroll 已补 [-1]，与多数 CRUD 对齐。"""
    crud_dir = PLUGIN_ROOT / 'crud'
    sentinels: dict[str, str] = {}
    for path in sorted(crud_dir.glob('*.py')):
        text = path.read_text(encoding='utf-8')
        if 'site_ids is not None' not in text and 'site_ids' not in text:
            continue
        if 'list(site_ids) or [-1]' in text or 'list(site_ids) or [-1]' in text:
            sentinels[path.name] = '[-1]'
        elif 'list(site_ids) if site_ids else [0]' in text:
            sentinels[path.name] = '[0]'
        elif 'site_id.in_(site_ids)' in text:
            sentinels[path.name] = 'raw-in'
    assert sentinels.get('site.py') == '[-1]'
    assert sentinels.get('rider.py') == '[-1]'
    assert sentinels.get('adjustment.py') == '[-1]'
    assert sentinels.get('settle_period.py') == '[-1]'
    assert sentinels.get('advance.py') == '[-1]'
    assert sentinels.get('order.py') == '[0]'
    assert sentinels.get('import_batch.py') == '[0]'
    assert sentinels.get('payroll.py') == '[-1]'


def test_audit_list_has_no_site_predicate() -> None:
    """缺口 #3 合同：审计列表仍不接收站点范围。"""
    text = (PLUGIN_ROOT / 'service' / 'audit_service.py').read_text(encoding='utf-8')
    assert 'get_visible_site_ids' not in text
    assert 'site_ids' not in text
    assert 'assert_site_visible' not in text
    crud = (PLUGIN_ROOT / 'crud' / 'audit_log.py').read_text(encoding='utf-8')
    assert 'site_id' not in crud

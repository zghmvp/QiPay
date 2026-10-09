"""审计站点提示与手机号打码。不连数据库。"""

from pathlib import Path

from backend.plugin.rider_salary.utils.audit import audit_site_hint, mask_audit_phones

_PATCH = Path(__file__).resolve().parents[1] / 'sql' / 'patch' / '005_audit_log_site.sql'


def test_mask_mobile_middle_four() -> None:
    """11 位手机号保留前 3 后 4。"""
    assert mask_audit_phones('13812348000') == '138****8000'
    assert mask_audit_phones('13900002222') == '139****2222'
    assert mask_audit_phones('联系 13812348000 即可') == '联系 138****8000 即可'


def test_mask_nested_snapshot_keeps_job_no() -> None:
    """快照里的手机号打码，工号和已经打过码的文本不动。"""
    payload = {
        'job_no': 'D5A001',
        'phone': '13812348000',
        'after': {'remark': '备用 13900002222', 'nested': ['13812348000']},
        'amount': 12,
    }
    masked = mask_audit_phones(payload)
    assert masked['job_no'] == 'D5A001'
    assert masked['phone'] == '138****8000'
    assert masked['after']['remark'] == '备用 139****2222'
    assert masked['after']['nested'] == ['138****8000']
    assert masked['amount'] == 12
    assert mask_audit_phones('138****8000') == '138****8000'
    assert payload['phone'] == '13812348000'


def test_audit_site_hint_global_and_direct() -> None:
    """方案和科目不回查；日标记、生成周期、导出订单的对象 ID 就是站点。"""
    assert audit_site_hint(target_type='subject', target_id=9, action='创建科目') == (None, False)
    assert audit_site_hint(target_type='plan', target_id=3, action='创建方案') == (None, False)
    assert audit_site_hint(target_type='plan_version', target_id=4, action='启用方案') == (None, False)
    assert audit_site_hint(target_type='site', target_id='12', action='创建站点') == (12, False)
    assert audit_site_hint(target_type='day_flag', target_id=7, action='更新日标记') == (7, False)
    assert audit_site_hint(target_type='period', target_id=5, action='生成周期') == (5, False)
    assert audit_site_hint(target_type='order', target_id=6, action='导出订单') == (6, False)
    assert audit_site_hint(target_type='rider', target_id=8, action='创建骑手') == (None, True)
    assert audit_site_hint(target_type='period', target_id=5, action='锁账') == (None, True)
    assert audit_site_hint(target_type='order', target_id=6, action='订单纠错') == (None, True)
    assert audit_site_hint(target_type='rider', target_id='不是数字', action='创建骑手') == (None, False)


def test_audit_site_patch_backfills_without_leading_comment() -> None:
    """补丁按对象类型回填，全局对象不写站点，文件开头不是注释。"""
    text = _PATCH.read_text(encoding='utf-8')
    lowered = text.lower()
    assert not text.lstrip().startswith('--')
    assert 'add column if not exists site_id' in lowered
    assert 'ix_rs_audit_log_site_id' in text
    assert "target_type = 'rider'" in text
    assert "target_type in ('rider_plan_binding', 'binding')" in text
    assert "target_type = 'payroll'" in text
    assert "action = '生成周期'" in text
    assert "target_type = 'subject'" not in text
    assert "target_type = 'plan'" not in text
    assert 'site_id is null' in text

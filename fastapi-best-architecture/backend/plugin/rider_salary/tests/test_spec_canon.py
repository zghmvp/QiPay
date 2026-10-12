"""P7-03：科目编码、5/5.5/6 阶梯第三档、反冲权限与库和预设一致。"""

import json
import re

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.engine.compiler import FORMULA_TEMPLATES
from backend.plugin.rider_salary.enums import RiderStatus
from backend.plugin.rider_salary.service.adjustment_service import (
    _PREV_DIFF_CODES,
    AdjustmentService,
    adjustment_employment_error,
)

_PLUGIN = Path(__file__).resolve().parents[1]
_WORKSPACE = _PLUGIN.parents[3]
_INIT_SQL = [
    _PLUGIN / 'sql' / 'postgresql' / 'init.sql',
    _PLUGIN / 'sql' / 'postgresql' / 'init_snowflake.sql',
    _PLUGIN / 'sql' / 'mysql' / 'init.sql',
    _PLUGIN / 'sql' / 'mysql' / 'init_snowflake.sql',
]
_PRESETS = (
    _WORKSPACE
    / 'fastapi-best-architecture-ui'
    / 'apps'
    / 'web-antdv-next'
    / 'src'
    / 'plugins'
    / 'rider-salary'
    / 'constants'
    / 'plan-presets.json'
)
_DOC_PATHS = [
    _WORKSPACE / 'docs' / '设计' / '00-架构决策纲要.md',
    _WORKSPACE / 'docs' / '设计' / '01-产品方案.md',
    _WORKSPACE / 'docs' / '设计' / '04-薪资方案案例库.md',
]
_SUBJECT_ROW = re.compile(
    r"\(\d+, '([A-Z0-9_]+)', '[^']*', '(bonus|penalty)', '(fixed|formula)', "
    r"null, (?:true|false|1|0), '(daily|period|both)'"
)
_CANON = {
    'PREV_DIFF': ('bonus', 'formula', 'period'),
    'BASE_UNIT_PRICE': ('bonus', 'formula', 'daily'),
    'GUARANTEE_TOPUP': ('bonus', 'formula', 'period'),
    'BASE_SALARY': ('bonus', 'fixed', 'period'),
    'INSURANCE_DEDUCT': ('penalty', 'fixed', 'period'),
    'COMMISSION': ('bonus', 'formula', 'period'),
}
_OWNER_ROLES = {'92002', '92003', '2060000000000092002', '2060000000000092003'}
_ADMIN_ROLES = {'92001', '2060000000000092001'}
_LADDER_PRESETS = {'C06', 'C07', 'C12', 'C17'}


class _Subject:
    def __init__(self, code: str) -> None:
        self.code = code


def _subjects(sql: str) -> dict[str, tuple[str, str, str]]:
    return {code: (direction, fee_mode, grain) for code, direction, fee_mode, grain in _SUBJECT_ROW.findall(sql)}


def _menu_ids(sql: str, title: str, perm: str) -> set[str]:
    pattern = re.compile(rf"\((\d+), '{title}'[^)]*'{perm}'")
    return set(pattern.findall(sql))


def _role_menus(sql: str) -> list[tuple[str, str]]:
    return [(role, menu) for _pk, role, menu in re.findall(r'\((\d+), (\d+), (\d+)\)', sql)]


def test_subject_seed_matches_canon() -> None:
    """四份初始化脚本使用同一套内置科目编码、计费方式和入账粒度。"""
    for path in _INIT_SQL:
        rows = _subjects(path.read_text(encoding='utf-8'))
        assert rows, path
        for code, expected in _CANON.items():
            assert rows[code] == expected, (path.name, code, rows.get(code))
        assert all(grain != 'both' for _direction, _fee, grain in rows.values()), path.name
        text = path.read_text(encoding='utf-8')
        assert "'PRIOR_DIFF'" not in text
        assert re.search(r"'BASE_UNIT'(?!_)", text) is None
        assert re.search(r"'GUARANTEE'(?!_)", text) is None


def test_site_owner_cannot_reverse_in_seed() -> None:
    """反冲只绑薪资管理员；站点负责人仍有锁账和标记发薪。"""
    for path in _INIT_SQL:
        sql = path.read_text(encoding='utf-8')
        bindings = _role_menus(sql)
        reverse_ids = _menu_ids(sql, '反冲补发', 'rs:period:reverse')
        lock_ids = _menu_ids(sql, '锁账', 'rs:period:lock')
        paid_ids = _menu_ids(sql, '标记发薪', 'rs:period:mark-paid')
        assert reverse_ids and lock_ids and paid_ids
        reverse_roles = {role for role, menu in bindings if menu in reverse_ids}
        assert reverse_roles <= _ADMIN_ROLES
        assert reverse_roles & _ADMIN_ROLES
        assert not (reverse_roles & _OWNER_ROLES)
        owner_menus = {menu for role, menu in bindings if role in _OWNER_ROLES}
        assert owner_menus & lock_ids
        assert owner_menus & paid_ids
        assert not (owner_menus & reverse_ids)


def test_prev_diff_whitelist_accepts_library_code() -> None:
    """负金额只认 PREV_DIFF 与已有别名，不认文档旧编码；离职日当天仍可补录。"""
    assert frozenset({'PREV_DIFF', 'PREV_PERIOD_ADJ'}) == _PREV_DIFF_CODES
    AdjustmentService._validate_amount(_Subject('PREV_DIFF'), Decimal('-12.50'))
    AdjustmentService._validate_amount(_Subject('PREV_PERIOD_ADJ'), Decimal(3))
    with pytest.raises(errors.RequestError, match='金额不能为 0'):
        AdjustmentService._validate_amount(_Subject('PREV_DIFF'), Decimal(0))
    with pytest.raises(errors.RequestError, match='金额必须大于 0'):
        AdjustmentService._validate_amount(_Subject('PRIOR_DIFF'), Decimal(-1))
    leave = date(2026, 10, 15)
    assert adjustment_employment_error(RiderStatus.resigned, leave, leave) is None
    assert adjustment_employment_error(RiderStatus.resigned, leave, date(2026, 10, 16)) is not None


def test_presets_and_formula_skeleton_use_library_ladder() -> None:
    """5/5.5/6 阶梯第三档起点为 700，预设科目编码都在种子里。"""
    catalog = json.loads(_PRESETS.read_text(encoding='utf-8'))
    seeded = _subjects(_INIT_SQL[0].read_text(encoding='utf-8'))
    seen: set[str] = set()
    for preset in catalog['presets']:
        for item in preset['items']:
            assert item['subject_code'] in seeded
            formula = item['formula_json']
            if formula.get('类型') != '阶梯':
                continue
            values = [tier['值'] for tier in formula['档位']]
            if values != [5, 5.5, 6]:
                continue
            assert formula['档位'][1]['上限'] == 700
            assert formula['档位'][2]['下限'] == 700
            seen.add(preset['id'])
    assert seen == _LADDER_PRESETS
    ladder = next(item for item in FORMULA_TEMPLATES if item['type'] == '阶梯')
    tiers = ladder['skeleton']['档位']
    assert [tier['值'] for tier in tiers] == [5, 5.5, 6]
    assert tiers[1]['上限'] == 700
    assert tiers[2]['下限'] == 700


def test_design_docs_drop_obsolete_codes_and_ladder_bound() -> None:
    """设计文档不再把旧编码或 600 档起点写成现行规格。"""
    obsolete = ('`BASE_UNIT`', '`GUARANTEE`', '`BONUS_RUSH`', '`NIGHT`', '`PENALTY_')
    stale_bounds = ('300–600', '[300,600)', '600+ → 6', '"上限":600')
    for path in _DOC_PATHS:
        text = path.read_text(encoding='utf-8')
        for token in stale_bounds:
            assert token not in text, (path.name, token)
        for line in text.splitlines():
            if '不是' in line or '废弃编码' in line:
                continue
            assert '`PRIOR_DIFF`' not in line, (path.name, line)
            for token in obsolete:
                assert token not in line, (path.name, token)

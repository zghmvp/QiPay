"""案例库 C01–C18 黄金夹具。

期望金额来自 `docs/设计/04-薪资方案案例库.md`，C18 来自 `docs/设计/01-产品方案.md` §4.3。
方案项来自管理端 `constants/plan-presets.json`，与 `plan-presets.ts` 共用。

5/5.5/6 阶梯的第三档起点：产品方案写 600，预设写 700。案例库给出的单量
（420、520、段内 20、周期 300）都落在第二档内，两边金额相同，因此这里不断言第三档起点。
"""

from decimal import Decimal
from typing import Any

import pytest

from backend.plugin.rider_salary.tests.golden.support import PRESET_TS_PATH, load_casebook, load_catalog, run_case

CASEBOOK = load_casebook()
CATALOG = load_catalog()
CASE_ROWS = [[case['id']] for case in CASEBOOK['cases']]
REQUIRED = ['FIX_C03', 'FIX_C04', 'FIX_C05A', 'FIX_C11', 'FIX_C17']


@pytest.mark.parametrize(['case_id'], CASE_ROWS)
def test_case_library_golden(case_id: str) -> None:
    """方案 JSON + 订单，断言案例库期望的应发与实发。"""
    case = _case(case_id)
    result = run_case(case, CATALOG)
    for key, raw in case['expect'].items():
        actual = getattr(result, key)
        assert actual == Decimal(str(raw)), f'{case_id}.{key} 期望 {raw}，实际 {actual}'


def test_required_fixtures_are_present() -> None:
    """验收要求的夹具都在用例表里。"""
    ids = {case['id'] for case in CASEBOOK['cases']}
    missing = [item for item in REQUIRED if item not in ids]
    assert not missing


def test_fix_c17_same_orders_different_fields() -> None:
    """FIX_C17：同一批订单，方案期内单量与周期有效单量结果不同。"""
    segment = run_case(_case('FIX_C17'), CATALOG)
    period_field = run_case(_case('FIX_C17_PERIOD_FIELD'), CATALOG)
    assert segment.gross == Decimal('100.00')
    assert period_field.gross == Decimal('1650.00')
    assert segment.gross != period_field.gross


def test_catalog_ids_cover_c01_to_c17() -> None:
    """共用目录覆盖 C01–C17。C18 由 C02 与 C17 两段拼出，不单列预设。"""
    ids = [preset['id'] for preset in CATALOG['presets']]
    assert ids == [f'C{index:02d}' for index in range(1, 18)]


def test_frontend_presets_use_shared_json() -> None:
    """管理端预设从同一份 JSON 加载，避免和黄金夹具各写一份。"""
    text = PRESET_TS_PATH.read_text(encoding='utf-8')
    assert "from './plan-presets.json'" in text


def _case(case_id: str) -> dict[str, Any]:
    return next(case for case in CASEBOOK['cases'] if case['id'] == case_id)

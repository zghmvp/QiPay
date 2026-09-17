"""重算任务状态机与夹具期望（DB-free）。"""

from __future__ import annotations

import json

from pathlib import Path

from backend.plugin.rider_salary.enums import RecalcJobSource, RecalcJobStatus

IMPORT_EXPECTED = json.loads(
    (Path(__file__).parent / 'fixtures' / 'ops-import-recalc-progress' / 'expected.json').read_text(encoding='utf-8')
)
STALE_EXPECTED = json.loads(
    (Path(__file__).parent / 'fixtures' / 'ops-stale-batch-recalc' / 'expected.json').read_text(encoding='utf-8')
)
CAL_EXPECTED = json.loads(
    (Path(__file__).parent / 'fixtures' / 'ops-calendar-no-plan-deeplink' / 'expected.json').read_text(encoding='utf-8')
)


def test_recalc_job_status_labels_match_fixture() -> None:
    expected_statuses = IMPORT_EXPECTED['expected']['statuses']
    expected_labels = IMPORT_EXPECTED['expected']['status_labels']
    assert [s.value for s in RecalcJobStatus] == expected_statuses
    assert [s.label for s in RecalcJobStatus] == expected_labels
    assert IMPORT_EXPECTED['expected']['no_celery'] is True
    assert IMPORT_EXPECTED['expected']['failed_retryable'] is True
    assert IMPORT_EXPECTED['expected']['forbid_green_complete_when_no_plan_rider'] is True
    assert IMPORT_EXPECTED['expected']['partial_fail_copy'] == '部分失败'
    assert IMPORT_EXPECTED['expected']['goto_calc_sees_job_no'] == 'FIX_C17_R1'


def test_recalc_job_source_labels_chinese() -> None:
    assert RecalcJobSource.import_batch.label == '导入后重算'
    assert RecalcJobSource.stale_batch.label == '本站本月批量重算'


def test_stale_batch_fixture_contract() -> None:
    exp = STALE_EXPECTED['expected']
    assert exp['permission'] == 'rs:period:calculate'
    assert exp['button_text'] == '本站本月批量重算'
    assert '站点' in exp['confirm_contains']
    assert exp['forbid_green_complete_when_no_plan_rider'] is True
    assert exp['forbid_allow_empty_stale_pass'] is True
    assert exp['no_plan_job_no'] == 'FIX_C17_R1'


def test_calendar_deeplink_fixture_contract() -> None:
    exp = CAL_EXPECTED['expected']
    assert exp['cell_cta'] == '去绑方案'
    assert exp['deeplink_query']['tab'] == 'binding'
    assert '{rider_id}' in exp['deeplink_path_pattern']
    assert CAL_EXPECTED['rider_job_no'] == 'FIX_C17_R1'
    assert CAL_EXPECTED['no_plan_days'] == ['2026-09-15', '2026-09-16', '2026-09-17']


def test_fix_c17_seed_json_aligns_with_calendar_and_trial() -> None:
    """演示灌种契约：日历深链与分段试算共用 FIX_C17_R1。"""
    seed_path = Path(__file__).parent / 'fixtures' / 'trial-binding-segments' / 'seed.json'
    seed = json.loads(seed_path.read_text(encoding='utf-8'))
    trial_expected = json.loads(
        (Path(__file__).parent / 'fixtures' / 'trial-binding-segments' / 'expected.json').read_text(encoding='utf-8')
    )
    assert seed['rider']['job_no'] == CAL_EXPECTED['rider_job_no']
    assert seed['no_plan_days'] == CAL_EXPECTED['no_plan_days']
    assert seed['rider']['job_no'] == trial_expected['rider_job_no']
    assert seed['no_plan_days'] == trial_expected['no_plan_days']
    assert STALE_EXPECTED['min_stale_riders'] >= 2

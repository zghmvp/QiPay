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


def test_recalc_job_source_labels_chinese() -> None:
    assert RecalcJobSource.import_batch.label == '导入后重算'
    assert RecalcJobSource.stale_batch.label == '本站本月批量重算'


def test_stale_batch_fixture_contract() -> None:
    exp = STALE_EXPECTED['expected']
    assert exp['permission'] == 'rs:period:calculate'
    assert exp['button_text'] == '本站本月批量重算'
    assert '站点' in exp['confirm_contains']


def test_calendar_deeplink_fixture_contract() -> None:
    exp = CAL_EXPECTED['expected']
    assert exp['cell_cta'] == '去绑方案'
    assert exp['deeplink_query']['tab'] == 'binding'
    assert '{rider_id}' in exp['deeplink_path_pattern']

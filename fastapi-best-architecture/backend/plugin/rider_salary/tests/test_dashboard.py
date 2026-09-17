from datetime import date, datetime
from types import SimpleNamespace

from backend.plugin.rider_salary.crud.settle_period import SITE_LEVEL_RIDER_ID
from backend.plugin.rider_salary.schema.dashboard import DashboardAttentionBlock
from backend.plugin.rider_salary.service.dashboard_service import (
    abnormal_order_attention_item,
    build_period_attention_item,
    import_gap_attention_item,
    period_attention_rider_fields,
)
from backend.utils.timezone import timezone


def test_site_level_period_row_has_no_rider_name() -> None:
    fields = period_attention_rider_fields(SITE_LEVEL_RIDER_ID, SimpleNamespace(job_no='D5A001', name='张三'))
    assert fields['rider_id'] == SITE_LEVEL_RIDER_ID
    assert not fields['rider_name']
    assert not fields['rider_job_no']


def test_rider_level_period_row_fills_name() -> None:
    fields = period_attention_rider_fields(7, SimpleNamespace(job_no='D5A001', name='张三'))
    assert fields['rider_id'] == 7
    assert fields['rider_job_no'] == 'D5A001'
    assert fields['rider_name'] == '张三'


def test_due_and_stale_same_range_keep_own_period_id() -> None:
    rider = SimpleNamespace(job_no='D5A001', name='张三')
    due = build_period_attention_item(
        period_id=11,
        site_id=2,
        rider_id=7,
        rider=rider,
        range_text='09-01~09-15',
        days_left=2,
    )
    stale = build_period_attention_item(
        period_id=12,
        site_id=2,
        rider_id=SITE_LEVEL_RIDER_ID,
        rider=None,
        range_text='09-01~09-15',
        stale_count=3,
    )
    assert due['range'] == stale['range'] == '09-01~09-15'
    assert due['period_id'] == 11
    assert stale['period_id'] == 12
    assert due['rider_name'] == '张三'
    assert due['rider_job_no'] == 'D5A001'
    assert stale['rider_id'] == SITE_LEVEL_RIDER_ID
    assert not stale['rider_name']
    assert 'days_left' in due
    assert 'stale_count' in stale


def test_import_gap_item_has_site_and_that_day() -> None:
    item = import_gap_attention_item(site_id=2, site_name='朝阳站', day=date(2026, 9, 16))
    assert item == {'site_id': 2, 'site_name': '朝阳站', 'date': '2026-09-16'}
    assert set(item) == {'site_id', 'site_name', 'date'}


def test_abnormal_order_item_keeps_id_and_order_no() -> None:
    order_time = datetime(2026, 9, 16, 10, 0, tzinfo=timezone.tz_info)
    deliver_time = datetime(2026, 9, 16, 11, 10, tzinfo=timezone.tz_info)
    row = SimpleNamespace(
        id=88,
        order_no='ORD-0916-001',
        rider_id=7,
        status='abnormal',
        order_time=order_time,
        deliver_time=deliver_time,
    )
    item = abnormal_order_attention_item(row, SimpleNamespace(name='张三'))
    assert item['id'] == 88
    assert item['order_no'] == 'ORD-0916-001'
    assert item['rider_name'] == '张三'
    assert item['duration_min'] is not None


def test_attention_block_items_remain_open_dicts() -> None:
    block = DashboardAttentionBlock(
        key='due_periods',
        title='即将到期周期',
        count=1,
        items=[{'period_id': 11, 'rider_id': 7, 'rider_name': '张三'}],
        link='/rider-salary/period?status=open',
    )
    assert block.items[0]['rider_name'] == '张三'

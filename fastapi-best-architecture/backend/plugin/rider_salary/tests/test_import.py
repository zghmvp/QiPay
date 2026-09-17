from datetime import date, datetime
from pathlib import Path

import pytest

from backend.plugin.rider_salary.enums import ImportBatchStatus, OrderStatus
from backend.plugin.rider_salary.schema.import_batch import GetImportBatchDetail, GetImportBatchListItem
from backend.plugin.rider_salary.schema.order import ImportResult
from backend.plugin.rider_salary.service.import_service import (
    build_import_template,
    import_result_msg,
    resolve_import_batch_outcome,
    validate_row_format,
)
from backend.plugin.rider_salary.service.order_service import compute_biz_date, map_order_status
from backend.plugin.rider_salary.utils.excel import ExcelReadError, parse_cell_datetime, read_rows, write_workbook
from backend.utils.timezone import timezone

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
SAMPLE_XLSX = FIXTURES / '订单导入样例.xlsx'
SAMPLE_CSV = FIXTURES / '订单导入样例.csv'


def _aware(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.tz_info)


def test_template_can_be_parsed() -> None:
    content = build_import_template()
    rows = read_rows(content, '订单导入模板.xlsx')
    assert len(rows) == 1
    row = rows[0]
    assert row['site_code'] == 'CY01'
    assert row['job_no'] == 'RS001'
    assert row['order_no'] == 'ORD-DEMO-001'
    assert row['status'] == '已完成'
    assert row['_row'] == 2


def test_sample_xlsx_parsed() -> None:
    rows = read_rows(SAMPLE_XLSX.read_bytes(), '订单导入样例.xlsx')
    assert [row['order_no'] for row in rows] == [
        'ORD-0901-001',
        'ORD-0901-002',
        'ORD-0901-003',
        'ORD-0901-004',
        'ORD-0901-005',
    ]
    assert rows[0]['status'] == '已完成'
    assert rows[1]['status'] == '完成'
    assert rows[2]['status'] == '取消'
    assert rows[2]['deliver_time'] in {None, ''}
    assert rows[3]['status'] == '异常'
    assert rows[4]['status'] == '退款'


def test_sample_csv_parsed() -> None:
    rows = read_rows(SAMPLE_CSV.read_bytes(), '订单导入样例.csv')
    assert len(rows) == 5
    assert rows[0]['site_code'] == 'CY01'
    assert rows[1]['order_no'] == 'ORD-0901-002'


def test_missing_header_message() -> None:
    content = write_workbook([('订单明细', ['站点编码', '订单号'], [['CY01', 'ORD-1']])])
    with pytest.raises(ExcelReadError, match='模板表头不符，缺少列：') as exc_info:
        read_rows(content, 'bad.xlsx')
    assert '骑手工号' in exc_info.value.msg


def test_empty_file_message() -> None:
    headers = [
        '站点编码*',
        '骑手工号*',
        '订单号*',
        '配送距离(公里)*',
        '商品重量(斤)*',
        '下单时间*',
        '送达时间',
        '订单状态*',
        '订单金额',
        '备注',
    ]
    content = write_workbook([('订单明细', headers, [])])
    with pytest.raises(ExcelReadError, match='文件为空，请按模板填写后重新上传'):
        read_rows(content, 'empty.xlsx')


def test_unsupported_file_type() -> None:
    with pytest.raises(ExcelReadError, match='仅支持 Excel 或 CSV 文件'):
        read_rows(b'hello', 'notes.txt')


@pytest.mark.parametrize(
    ['raw', 'expected'],
    [
        ['已完成', OrderStatus.completed.value],
        ['完成', OrderStatus.completed.value],
        ['completed', OrderStatus.completed.value],
        ['COMPLETED', OrderStatus.completed.value],
        ['已取消', OrderStatus.cancelled.value],
        ['取消', OrderStatus.cancelled.value],
        ['cancelled', OrderStatus.cancelled.value],
        ['配送异常', OrderStatus.abnormal.value],
        ['异常', OrderStatus.abnormal.value],
        ['已退款', OrderStatus.refunded.value],
        ['退款', OrderStatus.refunded.value],
        ['refunded', OrderStatus.refunded.value],
        ['未知', None],
        ['', None],
    ],
)
def test_status_alias_mapping(raw: str, expected: str | None) -> None:
    assert map_order_status(raw) == expected


def test_validate_row_error_messages() -> None:
    assert validate_row_format({'site_code': '', 'job_no': 'RS001', 'order_no': 'A'}) == '站点编码不能为空'
    assert (
        validate_row_format({
            'site_code': 'CY01',
            'job_no': 'RS001',
            'order_no': 'A',
            'distance_km': -1,
            'weight_jin': 1,
            'order_time': '2026-09-01 12:00:00',
            'status': '已完成',
        })
        == '配送距离不能为负数'
    )
    assert (
        validate_row_format({
            'site_code': 'CY01',
            'job_no': 'RS001',
            'order_no': 'A',
            'distance_km': 1,
            'weight_jin': -0.1,
            'order_time': '2026-09-01 12:00:00',
            'status': '已完成',
        })
        == '商品重量不能为负数'
    )
    assert (
        validate_row_format({
            'site_code': 'CY01',
            'job_no': 'RS001',
            'order_no': 'A',
            'distance_km': 1,
            'weight_jin': 1,
            'order_time': '2026-09-01 12:00:00',
            'deliver_time': '2026-09-01 11:00:00',
            'status': '已完成',
        })
        == '送达时间不能早于下单时间'
    )
    assert (
        validate_row_format({
            'site_code': 'CY01',
            'job_no': 'RS001',
            'order_no': 'A',
            'distance_km': 1,
            'weight_jin': 1,
            'order_time': '2026-09-01 12:00:00',
            'status': '在途',
        })
        == '订单状态不合法，请填写已完成/已取消/配送异常/已退款'
    )


def test_biz_date_uses_deliver_date() -> None:
    order_time = _aware(2026, 9, 1, 21, 50)
    deliver_time = _aware(2026, 9, 1, 22, 18)
    assert compute_biz_date(order_time, deliver_time) == date(2026, 9, 1)


def test_biz_date_without_deliver_uses_order_date() -> None:
    order_time = _aware(2026, 9, 1, 21, 50)
    assert compute_biz_date(order_time, None) == date(2026, 9, 1)


def test_biz_date_cross_midnight_uses_deliver_date() -> None:
    order_time = _aware(2026, 9, 1, 23, 50)
    deliver_time = _aware(2026, 9, 2, 0, 15)
    assert compute_biz_date(order_time, deliver_time) == date(2026, 9, 2)


@pytest.mark.parametrize(
    ['raw'],
    [
        ['2026-09-01 12:00:00'],
        ['2026/9/1 8:00'],
        ['2026/09/01 08:00:00'],
    ],
)
def test_parse_datetime_formats(raw: str) -> None:
    parsed = parse_cell_datetime(raw)
    assert parsed.tzinfo == timezone.tz_info
    assert parsed.year == 2026
    assert parsed.month == 9
    assert parsed.day == 1


def test_parse_datetime_excel_serial() -> None:
    parsed = parse_cell_datetime(46266)  # 2026-09-01
    assert parsed.date() == date(2026, 9, 1)
    assert parsed.tzinfo == timezone.tz_info


def test_skip_errors_partial_keeps_success_and_failed_rows() -> None:
    success_rows, status, drop_prepared = resolve_import_batch_outcome(
        skip_errors=True,
        prepared_count=4,
        failed_rows=1,
    )
    assert drop_prepared is False
    assert success_rows == 4
    assert status == ImportBatchStatus.partial_failed.value
    msg = import_result_msg(status=status, success_rows=success_rows, failed_rows=1)
    assert '成功 4 行' in msg
    assert '失败 1 行' in msg
    assert '全部导入成功' not in msg
    assert '导入流程已完成' not in msg


def test_skip_errors_off_failed_row_is_all_or_nothing() -> None:
    success_rows, status, drop_prepared = resolve_import_batch_outcome(
        skip_errors=False,
        prepared_count=4,
        failed_rows=1,
    )
    assert drop_prepared is True
    assert success_rows == 0
    assert status == ImportBatchStatus.failed.value
    msg = import_result_msg(status=status, success_rows=success_rows, failed_rows=1)
    assert '未写入任何订单' in msg
    assert '全部导入成功' not in msg


def test_import_schemas_keep_success_and_failed_rows() -> None:
    for schema in (ImportResult, GetImportBatchDetail, GetImportBatchListItem):
        assert 'success_rows' in schema.model_fields
        assert 'failed_rows' in schema.model_fields
        assert schema.model_fields['success_rows'].description == '成功行数'
        assert schema.model_fields['failed_rows'].description == '失败行数'


def test_all_success_import_message_is_not_half_success() -> None:
    success_rows, status, drop_prepared = resolve_import_batch_outcome(
        skip_errors=True,
        prepared_count=5,
        failed_rows=0,
    )
    assert drop_prepared is False
    assert success_rows == 5
    assert status == ImportBatchStatus.success.value
    assert import_result_msg(status=status, success_rows=success_rows, failed_rows=0) == '导入完成'

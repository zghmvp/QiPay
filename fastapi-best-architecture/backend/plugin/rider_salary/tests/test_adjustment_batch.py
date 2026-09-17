from datetime import date
from decimal import Decimal

from backend.plugin.rider_salary.schema.adjustment import BatchAdjustmentItemParam
from backend.plugin.rider_salary.service.adjustment_service import (
    batch_adjustment_message,
    is_blank_batch_adjustment_row,
    is_complete_batch_adjustment_row,
    is_incomplete_batch_adjustment_row,
    partition_batch_adjustment_items,
)


def _item(
    *,
    rider_id: int | None = None,
    biz_date: date | None = None,
    subject_id: int | None = None,
    amount: Decimal | None = None,
    remark: str | None = None,
) -> BatchAdjustmentItemParam:
    return BatchAdjustmentItemParam(
        rider_id=rider_id,
        biz_date=biz_date,
        subject_id=subject_id,
        amount=amount,
        remark=remark,
    )


def test_blank_new_row_is_not_incomplete() -> None:
    blank = _item()
    assert is_blank_batch_adjustment_row(blank) is True
    assert is_incomplete_batch_adjustment_row(blank) is False
    assert is_complete_batch_adjustment_row(blank) is False


def test_half_filled_rider_date_without_subject_is_incomplete() -> None:
    half = _item(rider_id=11, biz_date=date(2026, 9, 1))
    assert is_blank_batch_adjustment_row(half) is False
    assert is_incomplete_batch_adjustment_row(half) is True
    assert is_complete_batch_adjustment_row(half) is False


def test_partition_skips_incomplete_and_ignores_blank() -> None:
    complete = _item(
        rider_id=11,
        biz_date=date(2026, 9, 1),
        subject_id=3,
        amount=Decimal('10.00'),
        remark='全勤',
    )
    complete_2 = _item(
        rider_id=12,
        biz_date=date(2026, 9, 2),
        subject_id=4,
        amount=Decimal('5.00'),
        remark='超时',
    )
    half = _item(rider_id=11, biz_date=date(2026, 9, 3))
    rows, skipped = partition_batch_adjustment_items([complete, half, _item(), complete_2])
    assert skipped == 1
    assert len(rows) == 2
    assert [item.rider_id for item in rows] == [11, 12]


def test_batch_message_names_skip_m_not_all_success() -> None:
    text = batch_adjustment_message(created_count=2, skipped_incomplete_count=1)
    assert '已录入 2 条' in text
    assert '跳过未完整 1 条' in text
    assert '批量录入成功' not in text
    assert '整表' not in text
    zero_skip = batch_adjustment_message(created_count=2, skipped_incomplete_count=0)
    assert zero_skip == '已录入 2 条'
    assert '批量录入成功' not in zero_skip

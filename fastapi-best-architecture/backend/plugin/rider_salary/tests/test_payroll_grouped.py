from decimal import Decimal
from types import SimpleNamespace

from backend.plugin.rider_salary.enums import DetailSource
from backend.plugin.rider_salary.schema.payroll import GetPayrollDetailItem
from backend.plugin.rider_salary.service.payroll_service import (
    ADVANCE_SUBJECT_ID,
    build_advance_lines,
    build_subject_breakdown,
    extract_adjustment_id,
    extract_advance_id,
    gross_from_breakdown,
)
from backend.plugin.rider_salary.utils.money import q2

D = Decimal


def _detail(**kwargs) -> GetPayrollDetailItem:
    base = {
        'rider_id': 1,
        'stage': 'per_order',
        'subject_id': 1,
        'amount': D('10.00'),
        'include_in_gross': True,
        'source': DetailSource.formula.value,
    }
    base.update(kwargs)
    return GetPayrollDetailItem.model_validate(base)


def test_extract_advance_id_from_trace() -> None:
    assert extract_advance_id({'advance_id': 88}) == 88
    assert extract_advance_id({'变量': {'预支单ID': 99}}) == 99
    assert extract_advance_id(None) is None
    assert extract_adjustment_id({'adjustment_id': 7}) == 7


def test_subject_breakdown_sums_and_sources() -> None:
    items = [
        _detail(subject_id=1, subject_name='基础配送费', amount=D('5.00'), source='formula'),
        _detail(subject_id=1, subject_name='基础配送费', amount=D('3.50'), source='formula'),
        _detail(
            subject_id=2,
            subject_name='客诉',
            amount=D('-2.00'),
            source='manual',
            include_in_gross=True,
        ),
        _detail(
            subject_id=0,
            subject_name='预支抵扣',
            amount=D('-4.00'),
            source='advance',
            include_in_gross=False,
            calc_trace={'advance_id': 12},
            advance_id=12,
        ),
    ]
    breakdown = build_subject_breakdown(items)
    by_sid = {row.subject_id: row for row in breakdown}
    assert by_sid[1].amount_sum == q2(D('8.50'))
    assert by_sid[1].line_count == 2
    assert by_sid[1].sources == ['formula']
    assert by_sid[2].amount_sum == q2(D('-2.00'))
    assert 'manual' in by_sid[2].sources
    assert by_sid[ADVANCE_SUBJECT_ID].sources == ['advance']
    assert gross_from_breakdown(breakdown) == q2(D('6.50'))


def test_advance_lines_from_details() -> None:
    items = [
        _detail(
            subject_id=0,
            amount=D('-30.00'),
            source='advance',
            include_in_gross=False,
            calc_trace={'advance_id': 5, '变量': {'剩余': 70}},
            advance_id=5,
        )
    ]
    lines = build_advance_lines(items)
    assert len(lines) == 1
    assert lines[0].advance_id == 5
    assert lines[0].amount == q2(D('30.00'))
    assert lines[0].remaining_after == q2(D('70.00'))


def test_gross_excludes_advance_even_if_flagged() -> None:
    items = [
        _detail(subject_id=1, amount=D('100.00'), source='formula'),
        _detail(
            subject_id=0,
            amount=D('-20.00'),
            source='advance',
            include_in_gross=True,
            subject_name='预支抵扣',
        ),
    ]
    breakdown = build_subject_breakdown(items)
    assert gross_from_breakdown(breakdown) == q2(D('100.00'))


def test_detail_item_accepts_enrichment_fields() -> None:
    item = GetPayrollDetailItem.model_validate(
        SimpleNamespace(
            id=1,
            payroll_id=2,
            rider_id=3,
            biz_date=None,
            stage='daily',
            plan_version_id=9,
            plan_item_id=8,
            subject_id=7,
            order_id=6,
            amount=D('1.00'),
            include_in_gross=True,
            source='formula',
            calc_trace=None,
            name='夜班',
            order_no='O1',
            subject_name='夜班补贴',
            subject_code='NIGHT',
            plan_item_name='夜班',
            plan_version_name='标准A',
            advance_id=None,
            adjustment_id=None,
        )
    )
    assert item.subject_name == '夜班补贴'
    assert item.order_no == 'O1'

"""P6-18 预支台账、成本汇总、公告置顶。

台账合计必须与 ADVANCE_LEDGER_CONSISTENCY_SQL 在同一批行上的结果一致。
下面这组行的 SQL 结果写死在 EXPECTED_LEDGER_SQL_RESULT：
发放 1500.00 = 抵扣 900.00 + 结转 600.00，差额 0.00。
已删除的已发放、未发放的预支不计入。结转为空按 0。

成本只加总 payroll_view 挑出的有效单。
"""

import sqlite3

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import anyio

from sqlalchemy.dialects import postgresql

from backend.plugin.rider_salary.crud.notice import notice_dao, notice_sort_key
from backend.plugin.rider_salary.enums import AdvanceStatus, PayrollKind, PayrollStatus
from backend.plugin.rider_salary.service.audit_service import AUDIT_EXPORT_HEADERS, audit_export_cells
from backend.plugin.rider_salary.service.report_service import (
    ADVANCE_LEDGER_CONSISTENCY_SQL,
    summarize_advance_ledger,
    summarize_site_month_cost,
)
from backend.plugin.rider_salary.utils.audit import mask_audit_phones
from backend.plugin.rider_salary.utils.money import q2

# 一致性 SQL 在 _ledger_rows() 上的结果。发放 = 抵扣 + 结转，差额为 0。
EXPECTED_LEDGER_SQL_RESULT = (
    Decimal('1500.00'),
    Decimal('900.00'),
    Decimal('600.00'),
    Decimal('0.00'),
)


def _advance(**kwargs: object) -> SimpleNamespace:
    data: dict[str, object] = {
        'id': 1,
        'rider_id': 2,
        'site_id': 3,
        'amount': Decimal('0.00'),
        'deducted_amount': Decimal('0.00'),
        'remaining_amount': Decimal('0.00'),
        'status': AdvanceStatus.paid.value,
        'deleted': 0,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _ledger_rows() -> list[SimpleNamespace]:
    return [
        _advance(
            id=1, amount=Decimal('1000.00'), deducted_amount=Decimal('400.00'), remaining_amount=Decimal('600.00')
        ),
        _advance(id=2, amount=Decimal('200.00'), deducted_amount=Decimal('200.00'), remaining_amount=Decimal('0.00')),
        _advance(id=3, amount=Decimal('300.00'), deducted_amount=Decimal('300.00'), remaining_amount=None),
        _advance(
            id=4,
            amount=Decimal('50.00'),
            deducted_amount=Decimal('0.00'),
            remaining_amount=Decimal('50.00'),
            deleted=4,
        ),
        _advance(
            id=5,
            amount=Decimal('80.00'),
            deducted_amount=Decimal('0.00'),
            remaining_amount=Decimal('80.00'),
            status=AdvanceStatus.pending.value,
        ),
    ]


def _insert_ledger(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table rs_advance (
            id integer primary key,
            amount numeric,
            deducted_amount numeric,
            remaining_amount numeric,
            status text,
            deleted integer
        )
        """
    )
    for row in _ledger_rows():
        conn.execute(
            """
            insert into rs_advance (id, amount, deducted_amount, remaining_amount, status, deleted)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                row.id,
                str(row.amount),
                str(row.deducted_amount),
                None if row.remaining_amount is None else str(row.remaining_amount),
                row.status,
                row.deleted,
            ),
        )


def _as_money(value: object) -> Decimal:
    return q2(Decimal(str(value)))


def test_ledger_totals_match_consistency_sql() -> None:
    """合计与一致性 SQL 的结果相同，且发放 = 抵扣 + 结转。"""
    conn = sqlite3.connect(':memory:')
    _insert_ledger(conn)
    issued, deducted, carried, gap = conn.execute(ADVANCE_LEDGER_CONSISTENCY_SQL).fetchone()
    sql_result = (_as_money(issued), _as_money(deducted), _as_money(carried), _as_money(gap))
    assert sql_result == EXPECTED_LEDGER_SQL_RESULT

    totals, lines = summarize_advance_ledger(_ledger_rows())
    assert (totals.issued, totals.deducted, totals.carried, totals.gap) == EXPECTED_LEDGER_SQL_RESULT
    assert totals.balanced is True
    assert totals.issued == totals.deducted + totals.carried
    assert [line.advance_id for line in lines] == [1, 2, 3]
    assert "status = 'paid'" in ADVANCE_LEDGER_CONSISTENCY_SQL
    assert 'deleted = 0' in ADVANCE_LEDGER_CONSISTENCY_SQL
    conn.close()


def test_ledger_gap_matches_sql_when_unbalanced() -> None:
    """结转少记时，差额与 SQL 一致，台账不平。"""
    rows = [
        _advance(id=8, amount=Decimal('100.00'), deducted_amount=Decimal('40.00'), remaining_amount=Decimal('50.00')),
    ]
    conn = sqlite3.connect(':memory:')
    conn.execute(
        """
        create table rs_advance (
            id integer primary key,
            amount numeric,
            deducted_amount numeric,
            remaining_amount numeric,
            status text,
            deleted integer
        )
        """
    )
    conn.execute(
        'insert into rs_advance values (8, 100, 40, 50, ?, 0)',
        (AdvanceStatus.paid.value,),
    )
    sql_gap = _as_money(conn.execute(ADVANCE_LEDGER_CONSISTENCY_SQL).fetchone()[3])
    totals, _lines = summarize_advance_ledger(rows)
    assert sql_gap == Decimal('10.00')
    assert totals.gap == sql_gap
    assert totals.balanced is False
    conn.close()


def _slip(**kwargs: object) -> SimpleNamespace:
    data: dict[str, object] = {
        'id': 1,
        'period_id': 1,
        'rider_id': 2,
        'kind': PayrollKind.normal.value,
        'status': PayrollStatus.finalized.value,
        'deleted': 0,
        'reversed': False,
        'reversed_of_id': None,
        'stale': False,
        'calc_version': 1,
        'net': Decimal('0.00'),
        'gross': Decimal('0.00'),
        'advance_deduction': Decimal('0.00'),
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def test_cost_summary_uses_effective_payroll_only() -> None:
    """已被反冲的原单、反冲单和作废单不进成本；有效补发才计入。"""
    periods = [
        SimpleNamespace(id=1, site_id=10, start_date=date(2026, 9, 1), deleted=0),
        SimpleNamespace(id=2, site_id=11, start_date=date(2026, 10, 16), deleted=0),
        SimpleNamespace(id=3, site_id=10, start_date=date(2026, 9, 16), deleted=0),
    ]
    payrolls = [
        _slip(
            id=1,
            period_id=1,
            rider_id=2,
            gross=Decimal('100.00'),
            net=Decimal('90.00'),
            reversed=True,
            advance_deduction=Decimal('10.00'),
        ),
        _slip(
            id=2,
            period_id=1,
            rider_id=2,
            kind=PayrollKind.supplement.value,
            calc_version=2,
            gross=Decimal('80.00'),
            net=Decimal('70.00'),
            advance_deduction=Decimal('5.00'),
        ),
        _slip(
            id=4,
            period_id=1,
            rider_id=2,
            kind=PayrollKind.reversal.value,
            gross=Decimal('-100.00'),
            net=Decimal('-90.00'),
        ),
        _slip(
            id=5,
            period_id=2,
            rider_id=3,
            status=PayrollStatus.voided.value,
            gross=Decimal('999.00'),
            net=Decimal('999.00'),
        ),
        _slip(
            id=6,
            period_id=3,
            rider_id=4,
            gross=Decimal('20.00'),
            net=Decimal('20.00'),
            advance_deduction=Decimal('0.00'),
        ),
    ]
    rows = summarize_site_month_cost(periods, payrolls)
    assert [(row.site_id, row.month, row.slip_count, row.gross, row.net, row.advance_deduction) for row in rows] == [
        (10, '2026-09', 2, Decimal('100.00'), Decimal('90.00'), Decimal('5.00')),
    ]


def test_pinned_notice_sorts_first() -> None:
    """置顶优先，同组内发布时间倒序，未发布的排在后面。"""
    early = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    late = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)
    notices = [
        SimpleNamespace(id=1, is_top=False, publish_time=late),
        SimpleNamespace(id=2, is_top=True, publish_time=early),
        SimpleNamespace(id=3, is_top=True, publish_time=late),
        SimpleNamespace(id=4, is_top=False, publish_time=None),
        SimpleNamespace(id=5, is_top=True, publish_time=late),
    ]
    ordered = sorted(notices, key=notice_sort_key)
    assert [item.id for item in ordered] == [5, 3, 2, 1, 4]
    assert ordered[0].is_top is True


def test_notice_list_orders_by_top_then_publish_time() -> None:
    async def _case() -> None:
        stmt = await notice_dao.get_select(title=None, status=None, site_id=None, site_ids=None)
        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        order_by = compiled.lower().split('order by', 1)[1]
        assert 'is_top desc' in order_by
        assert 'publish_time desc' in order_by
        assert 'nulls last' in order_by
        assert order_by.index('is_top') < order_by.index('publish_time')

    anyio.run(_case)


def test_audit_export_headers_and_phone_mask() -> None:
    assert AUDIT_EXPORT_HEADERS[0] == '操作时间'
    assert '变更前' in AUDIT_EXPORT_HEADERS
    masked = mask_audit_phones({
        'operate_time': '2026-10-01 09:00:00',
        'operator_name': '张三',
        'module': '预支审核',
        'action': '标记已发放',
        'target_type': 'advance',
        'target_id': '9',
        'target_label': '预支 9',
        'site_id': 3,
        'reason': None,
        'description': '联系 13812348000',
        'before': None,
        'after': {'phone': '13812348000'},
    })
    cells = audit_export_cells(masked)
    assert cells[9] == '联系 138****8000'
    assert '138****8000' in cells[11]
    assert '13812348000' not in cells[11]

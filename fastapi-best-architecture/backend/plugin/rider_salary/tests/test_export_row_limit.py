"""P5-06：导出和月历超过 5 万行时拒绝，生成时不先把全部行收成列表。"""

from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anyio
import pytest

from openpyxl import Workbook
from openpyxl.worksheet._write_only import WriteOnlyWorksheet
from sqlalchemy import select

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import OrderStatus
from backend.plugin.rider_salary.model.advance import RiderSalaryAdvance
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.service.advance_service import (
    _advance_dimension_ids,
    _iter_advance_export_rows,
    advance_service,
)
from backend.plugin.rider_salary.service.calendar_service import (
    _AdjustmentFold,
    _OrderFold,
    _fold_orders,
    assign_site_by_day,
    calendar_service,
)
from backend.plugin.rider_salary.service.export_service import export_service, period_export_upper_bound
from backend.plugin.rider_salary.service.order_service import _iter_order_export_rows, order_service
from backend.plugin.rider_salary.utils import excel as excel_module
from backend.plugin.rider_salary.utils.excel import (
    MAX_EXPORT_ROWS,
    StreamingWorkbook,
    append_streamed_rows,
    assert_export_row_limit,
    stream_rows,
    write_workbook,
)
from backend.utils.timezone import timezone


class _RowProbe:
    """只能逐个拉取的行源。若先 list()，第一次写入时已经全部取完。"""

    def __init__(self, total: int) -> None:
        self.total = total
        self.pulled = 0

    def __iter__(self) -> '_RowProbe':
        return self

    def __next__(self) -> list[int]:
        if self.pulled >= self.total:
            raise StopIteration
        self.pulled += 1
        return [self.pulled]


class _AsyncRows:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.index = 0

    def __aiter__(self) -> '_AsyncRows':
        return self

    async def __anext__(self) -> object:
        if self.index >= len(self.rows):
            raise StopAsyncIteration
        row = self.rows[self.index]
        self.index += 1
        return row


class _StreamDB:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.stream_calls = 0

    async def stream(self, stmt: object) -> _AsyncRows:
        self.stream_calls += 1
        return _AsyncRows(self.rows)

    async def scalars(self, stmt: object) -> object:
        raise AssertionError('不应把行装进 scalars().all()')

    def expunge(self, instance: object) -> None:
        return None


def test_limit_is_fifty_thousand_and_rejects_in_chinese() -> None:
    assert MAX_EXPORT_ROWS == 50_000
    with pytest.raises(errors.RequestError) as exc:
        assert_export_row_limit(MAX_EXPORT_ROWS + 1)
    assert exc.value.msg == '导出行数超过 5 万行上限，请缩小筛选范围后重试'
    assert_export_row_limit(MAX_EXPORT_ROWS)


def test_write_workbook_uses_write_only(monkeypatch: pytest.MonkeyPatch) -> None:
    flags: list[object] = []
    original = Workbook.__init__

    def wrapped(self: Workbook, *args: object, **kwargs: object) -> None:
        flags.append(kwargs.get('write_only'))
        original(self, *args, **kwargs)

    monkeypatch.setattr(Workbook, '__init__', wrapped)
    content = write_workbook([('明细', ['序号'], [['1']])])
    assert flags == [True]
    assert content[:2] == b'PK'


def test_write_workbook_appends_before_the_iterator_is_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = _RowProbe(6)
    seen: list[int] = []
    original = WriteOnlyWorksheet.append

    def spy(self: WriteOnlyWorksheet, row: object) -> None:
        seen.append(probe.pulled)
        original(self, row)

    monkeypatch.setattr(WriteOnlyWorksheet, 'append', spy)
    write_workbook([('明细', ['序号'], probe)])
    assert seen[0] == 0
    assert seen[1] == 1
    assert probe.pulled == 6


def test_write_workbook_stops_instead_of_reading_the_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(excel_module, 'MAX_EXPORT_ROWS', 3)
    probe = _RowProbe(100_000)
    with pytest.raises(errors.RequestError) as exc:
        write_workbook([('明细', ['序号'], probe)])
    assert '缩小筛选范围' in exc.value.msg
    assert probe.pulled == 4


def test_stream_rows_yields_before_the_source_is_exhausted() -> None:
    state = {'n': 0}

    class _Source:
        def __aiter__(self) -> '_Source':
            return self

        async def __anext__(self) -> tuple[int]:
            if state['n'] >= 4:
                raise StopAsyncIteration
            state['n'] += 1
            return (state['n'],)

    class _DB:
        def __init__(self) -> None:
            self.options: dict[str, object] = {}

        async def stream(self, stmt: object) -> _Source:
            self.options = stmt.get_execution_options()
            return _Source()

    async def _run() -> None:
        db = _DB()
        agen = stream_rows(db, select(RiderSalaryOrder).where(RiderSalaryOrder.id == -1))
        first = await agen.__anext__()
        assert first == (1,)
        assert state['n'] == 1
        assert db.options.get('yield_per') == excel_module.EXPORT_STREAM_YIELD

    anyio.run(_run)


def test_append_streamed_rows_does_not_collect_first() -> None:
    state = {'n': 0}

    async def _rows() -> AsyncIterator[list[int]]:
        for index in range(4):
            state['n'] += 1
            await anyio.sleep(0)
            yield [index]

    seen: list[int] = []

    async def _run() -> None:
        book = StreamingWorkbook()
        sheet = book.add_sheet('明细', ['序号'])
        original = book.append

        def spy(worksheet: object, row: object) -> None:
            seen.append(state['n'])
            original(worksheet, row)

        book.append = spy  # type: ignore[method-assign]
        await append_streamed_rows(book, sheet, _rows())
        content = book.to_bytes()
        assert content[:2] == b'PK'

    anyio.run(_run)
    assert seen[0] == 1
    assert state['n'] == 4


def test_order_export_rejects_without_reading_rows() -> None:
    async def _run() -> None:
        with (
            patch(
                'backend.plugin.rider_salary.service.order_service.get_visible_site_ids',
                new=AsyncMock(return_value={1}),
            ),
            patch(
                'backend.plugin.rider_salary.service.order_service._get_site',
                new=AsyncMock(return_value=SimpleNamespace(id=1, code='D5A', name='甲站')),
            ),
            patch(
                'backend.plugin.rider_salary.service.order_service.order_dao.get_select',
                new=AsyncMock(return_value=select(RiderSalaryOrder).where(RiderSalaryOrder.id == -1)),
            ),
            patch(
                'backend.plugin.rider_salary.service.order_service.count_statement',
                new=AsyncMock(return_value=MAX_EXPORT_ROWS + 1),
            ),
            patch(
                'backend.plugin.rider_salary.service.order_service.stream_scalars',
                side_effect=AssertionError('超限后不应读取订单'),
            ),
            patch(
                'backend.plugin.rider_salary.service.order_service._riders_for_order_export',
                new=AsyncMock(side_effect=AssertionError('超限后不应加载骑手')),
            ),
        ):
            with pytest.raises(errors.RequestError) as exc:
                await order_service.export(
                    db=SimpleNamespace(),
                    request=SimpleNamespace(),
                    site_id=1,
                    date_from=None,
                    date_to=None,
                    rider_id=None,
                )
        assert '缩小筛选范围' in exc.value.msg

    anyio.run(_run)


def test_order_rows_are_yielded_one_at_a_time() -> None:
    state = {'n': 0}
    moment = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.tz_info)

    def _order(index: int) -> SimpleNamespace:
        return SimpleNamespace(
            rider_id=1,
            order_no=f'N{index}',
            distance_km=Decimal('1.20'),
            weight_jin=Decimal('2.00'),
            order_time=moment,
            deliver_time=None,
            status='completed',
            amount=None,
            remark='',
            source='manual',
            biz_date=date(2026, 9, 1),
            is_locked=False,
        )

    async def _fake_stream(db: object, stmt: object) -> AsyncIterator[SimpleNamespace]:
        for index in range(4):
            state['n'] += 1
            await anyio.sleep(0)
            yield _order(index)

    site = SimpleNamespace(code='D5A', name='甲站')
    riders = {1: SimpleNamespace(job_no='A001', name='张三')}

    async def _run() -> None:
        with patch('backend.plugin.rider_salary.service.order_service.stream_scalars', _fake_stream):
            agen = _iter_order_export_rows(_StreamDB([]), select(RiderSalaryOrder), site, riders)
            first = await agen.__anext__()
        assert state['n'] == 1
        assert first[0] == 'D5A'
        assert first[4] == 'N0'

    anyio.run(_run)


def test_advance_export_rejects_without_reading_rows() -> None:
    async def _run() -> None:
        with (
            patch(
                'backend.plugin.rider_salary.service.advance_service.get_visible_site_ids',
                new=AsyncMock(return_value=None),
            ),
            patch(
                'backend.plugin.rider_salary.service.advance_service.advance_dao.get_select',
                new=AsyncMock(return_value=select(RiderSalaryAdvance).where(RiderSalaryAdvance.id == -1)),
            ),
            patch(
                'backend.plugin.rider_salary.service.advance_service.count_statement',
                new=AsyncMock(return_value=MAX_EXPORT_ROWS + 1),
            ),
            patch(
                'backend.plugin.rider_salary.service.advance_service.stream_rows',
                side_effect=AssertionError('超限后不应读取预支'),
            ),
            patch(
                'backend.plugin.rider_salary.service.advance_service.stream_scalars',
                side_effect=AssertionError('超限后不应读取预支'),
            ),
        ):
            with pytest.raises(errors.RequestError) as exc:
                await advance_service.export(
                    db=SimpleNamespace(),
                    request=SimpleNamespace(),
                    site_id=None,
                    status=None,
                    date_from=None,
                    date_to=None,
                )
        assert '缩小筛选范围' in exc.value.msg

    anyio.run(_run)


def test_advance_dimension_ids_stream_instead_of_listing() -> None:
    db = _StreamDB([(1, 3, None), (1, 3, 9), (2, 3, 9), (2, 4, None)])

    async def _run() -> None:
        rider_ids, site_ids, user_ids = await _advance_dimension_ids(
            db,
            select(RiderSalaryAdvance).where(RiderSalaryAdvance.deleted == 0),
        )
        assert rider_ids == {1, 2}
        assert site_ids == {3, 4}
        assert user_ids == {9}
        assert db.stream_calls == 1

    anyio.run(_run)


def test_advance_rows_are_yielded_one_at_a_time() -> None:
    state = {'n': 0}

    def _advance(index: int) -> SimpleNamespace:
        return SimpleNamespace(
            rider_id=1,
            site_id=3,
            approver_id=None,
            amount=Decimal('10.00'),
            reason=f'原因{index}',
            status='pending',
            submit_time=None,
            approve_time=None,
            paid_time=None,
            deducted_amount=Decimal('0.00'),
            remaining_amount=Decimal('10.00'),
        )

    async def _fake_stream(db: object, stmt: object) -> AsyncIterator[SimpleNamespace]:
        for index in range(4):
            state['n'] += 1
            await anyio.sleep(0)
            yield _advance(index)

    async def _run() -> None:
        with patch('backend.plugin.rider_salary.service.advance_service.stream_scalars', _fake_stream):
            agen = _iter_advance_export_rows(_StreamDB([]), select(RiderSalaryAdvance), ({}, {}, {}))
            first = await agen.__anext__()
        assert state['n'] == 1
        assert first[4] == '原因0'

    anyio.run(_run)


def test_period_export_rejects_before_loading_payrolls() -> None:
    loaded = {'payrolls': False}
    period = SimpleNamespace(
        id=8,
        site_id=2,
        rider_id=0,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )

    async def _load_visible(db: object, request: object, pk: int) -> tuple[object, object, None]:
        await anyio.sleep(0)
        return period, SimpleNamespace(name='甲站'), None

    async def _counts(self: object, db: object, period_row: object) -> tuple[int, int, int]:
        await anyio.sleep(0)
        return 0, MAX_EXPORT_ROWS + 1, 0

    async def _load_payrolls(*args: object, **kwargs: object) -> list[object]:
        await anyio.sleep(0)
        loaded['payrolls'] = True
        return []

    async def _run() -> None:
        with (
            patch(
                'backend.plugin.rider_salary.service.export_service.period_service._load_visible',
                _load_visible,
            ),
            patch(
                'backend.plugin.rider_salary.service.export_service.ExportService._period_export_counts',
                _counts,
            ),
            patch(
                'backend.plugin.rider_salary.service.export_service.payroll_dao.select_models_order',
                _load_payrolls,
            ),
        ):
            with pytest.raises(errors.RequestError) as exc:
                await export_service.export_period(db=SimpleNamespace(), request=SimpleNamespace(), pk=8)
        assert '缩小筛选范围' in exc.value.msg
        assert loaded['payrolls'] is False
        assert period_export_upper_bound(0, MAX_EXPORT_ROWS + 1, 0) == MAX_EXPORT_ROWS + 1

    anyio.run(_run)


def test_calendar_month_rejects_before_streaming_orders() -> None:
    db = _StreamDB([])
    db.scalar_values = [MAX_EXPORT_ROWS + 1, 0, 0, 0]

    async def _scalar(stmt: object) -> int:
        await anyio.sleep(0)
        return db.scalar_values.pop(0)

    db.scalar = _scalar
    rider = SimpleNamespace(id=7, site_id=3)

    async def _run() -> None:
        with patch(
            'backend.plugin.rider_salary.service.calendar_service.rider_dao.get',
            new=AsyncMock(return_value=rider),
        ):
            with pytest.raises(errors.RequestError) as exc:
                await calendar_service.build_month(db, rider.id, '2026-09')
        assert '缩小筛选范围' in exc.value.msg
        assert db.stream_calls == 0

    anyio.run(_run)


def test_calendar_day_rejects_before_listing_orders() -> None:
    db = _StreamDB([])
    db.scalar_values = [MAX_EXPORT_ROWS + 1, 0, 0, 0]

    async def _scalar(stmt: object) -> int:
        await anyio.sleep(0)
        return db.scalar_values.pop(0)

    db.scalar = _scalar

    async def _orders(*args: object, **kwargs: object) -> list[object]:
        await anyio.sleep(0)
        raise AssertionError('超限后不应把当日订单装进列表')

    async def _run() -> None:
        with (
            patch(
                'backend.plugin.rider_salary.service.calendar_service.rider_dao.get',
                new=AsyncMock(return_value=SimpleNamespace(id=7, site_id=3)),
            ),
            patch('backend.plugin.rider_salary.service.calendar_service._orders_in_range', _orders),
        ):
            with pytest.raises(errors.RequestError) as exc:
                await calendar_service.build_day(db, 7, date(2026, 9, 10))
        assert '缩小筛选范围' in exc.value.msg

    anyio.run(_run)


def test_fold_orders_streams_rows() -> None:
    day = date(2026, 9, 1)
    db = _StreamDB([
        (day, 2, OrderStatus.completed.value),
        (day, 2, OrderStatus.completed.value),
        (day, 1, 'cancelled'),
    ])

    async def _run() -> None:
        fold = await _fold_orders(db, 7, day, day)
        assert fold.count_by_day[day] == 3
        assert fold.valid_by_day[day] == 2
        assert fold.dominant_points() == [(day, 2)]
        assert db.stream_calls == 1

    anyio.run(_run)


def test_folded_site_points_match_assign_site_by_day() -> None:
    """换站日仍按订单次数选站点，空白日沿用前一个快照。"""
    raw = [
        (date(2026, 9, 1), 1),
        (date(2026, 9, 1), 1),
        (date(2026, 9, 14), 1),
        (date(2026, 9, 15), 2),
        (date(2026, 9, 15), 2),
        (date(2026, 9, 15), 1),
    ]
    fold = _OrderFold()
    for biz_date, site_id in raw:
        fold.add(biz_date, site_id, OrderStatus.completed.value)
    direct = assign_site_by_day(date(2026, 9, 1), date(2026, 9, 30), order_points=raw, fallback_site_id=9)
    folded = assign_site_by_day(
        date(2026, 9, 1),
        date(2026, 9, 30),
        order_points=fold.dominant_points(),
        fallback_site_id=9,
    )
    assert folded == direct
    assert [folded[date(2026, 9, day)] for day in range(1, 15)] == [1] * 14
    assert [folded[date(2026, 9, day)] for day in range(15, 31)] == [2] * 16

    day = date(2026, 9, 3)
    orders = _OrderFold()
    adjustments = _AdjustmentFold()
    orders.add(day, 1, OrderStatus.completed.value)
    adjustments.add(day, 2, 7, Decimal('1.00'))
    mixed = assign_site_by_day(
        day,
        day,
        order_points=orders.dominant_points(),
        adjustment_points=adjustments.dominant_points(),
        fallback_site_id=2,
    )
    assert mixed[day] == 1

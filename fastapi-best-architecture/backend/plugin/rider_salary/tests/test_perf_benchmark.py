"""P5-12：小样本性能基准。

默认 1 个站点、2 名骑手、每人 24 张订单（共 48 张），全部在内存里完成。
不连接、不写入共享库 ``fba``。Q-19 的全量规模只写在 ``docs/research/算薪性能基准.md``。

阈值只挡住数量级回退。它们不是 20 站 / 2000 骑手 / 日 6 万单的承诺。
"""

import statistics
import time

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import anyio
import pytest

from fastapi_pagination.api import set_page, set_params
from openpyxl import Workbook
from openpyxl.worksheet._write_only import WriteOnlyWorksheet
from starlette.requests import Request

from backend.common.pagination import _CustomPage, _CustomPageParams
from backend.plugin.rider_salary.engine.compiler import compile_condition, compile_formula
from backend.plugin.rider_salary.engine.segments import PlanItemView, Segment
from backend.plugin.rider_salary.enums import CalcStage, DetailSource, OrderStatus, SubjectDirection
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.site import RiderSalarySite
from backend.plugin.rider_salary.service.calc_service import CalcInput, run_calc_pipeline
from backend.plugin.rider_salary.service.export_service import export_service
from backend.plugin.rider_salary.service.order_service import order_service
from backend.plugin.rider_salary.service.payroll_service import payroll_service
from backend.plugin.rider_salary.utils.excel import EXPORT_STREAM_YIELD, StreamingWorkbook, append_streamed_rows
from backend.utils.timezone import timezone

# 改这两个常量可以在内存里放大样本。不要据此往 fba 灌数。
RIDER_COUNT = 2
ORDERS_PER_RIDER = 24
PERIOD_DAYS = 3
CALC_REPEATS = 5
LIST_PAGE_SIZES = (20, 40)
SITE_ID = 1
PERIOD_START = date(2026, 10, 1)

# 小样本阈值（毫秒 / 次数）。慢机器上仍应远低于这些上限。
CALC_MEDIAN_MS_MAX = 2_000
LIST_QUERY_MAX = 6
LIST_ELAPSED_MS_MAX = 1_000
EXPORT_ELAPSED_MS_MAX = 2_000

_MONEY = Decimal
_TZ = timezone.tz_info


def _median_ms(samples: list[float]) -> float:
    return statistics.median(samples) * 1000


def _compact(sql: str) -> str:
    return ' '.join(sql.lower().split())


def _sql_of(stmt: object) -> str:
    compile_ = getattr(stmt, 'compile', None)
    if compile_ is None:
        return _compact(str(stmt))
    try:
        rendered = str(compile_(compile_kwargs={'literal_binds': True}))
    except Exception:
        rendered = str(compile_())
    return _compact(rendered)


def _item(
    *,
    pk: int,
    subject_id: int,
    name: str,
    stage: str,
    sort_order: int,
    formula: dict[str, Any],
    condition: dict[str, Any] | None = None,
) -> PlanItemView:
    return PlanItemView(
        id=pk,
        subject_id=subject_id,
        name=name,
        stage=stage,
        sort_order=sort_order,
        condition_json=condition,
        formula_json=formula,
        condition_expr=compile_condition(condition, stage),
        formula_expr=compile_formula(formula, stage),
        enabled=True,
        direction=SubjectDirection.bonus.value,
        include_in_gross=True,
    )


def _benchmark_segment() -> Segment:
    """逐单、按日、周期各一项，让流水线走完三阶段。"""
    night = {
        '逻辑': '且',
        '条件': [{'字段': '送达时刻', '运算符': '在时段内', '值': ['22:00', '06:00']}],
    }
    end = PERIOD_START + timedelta(days=PERIOD_DAYS - 1)
    items = [
        _item(
            pk=1,
            subject_id=1,
            name='基础单价',
            stage=CalcStage.per_order.value,
            sort_order=10,
            formula={'类型': '固定金额', '金额': 4},
        ),
        _item(
            pk=2,
            subject_id=2,
            name='夜间补贴',
            stage=CalcStage.per_order.value,
            sort_order=20,
            condition=night,
            formula={'类型': '固定金额', '金额': 2},
        ),
        _item(
            pk=3,
            subject_id=3,
            name='距离补贴',
            stage=CalcStage.per_order.value,
            sort_order=30,
            formula={'类型': '表达式', '表达式': '配送距离 * 0.5'},
        ),
        _item(
            pk=4,
            subject_id=4,
            name='日单奖',
            stage=CalcStage.daily.value,
            sort_order=10,
            formula={'类型': '表达式', '表达式': '日单量 * 1'},
        ),
        _item(
            pk=5,
            subject_id=5,
            name='底薪',
            stage=CalcStage.period.value,
            sort_order=10,
            formula={'类型': '表达式', '表达式': '2000 * 方案生效天数 / 周期天数'},
        ),
        _item(
            pk=6,
            subject_id=6,
            name='提成',
            stage=CalcStage.period.value,
            sort_order=20,
            formula={
                '类型': '阶梯',
                '字段': '方案期内单量',
                '模式': '全量落档',
                '计价': '按单价',
                '档位': [
                    {'下限': 0, '上限': 10, '值': 5},
                    {'下限': 10, '上限': None, '值': 6},
                ],
            },
        ),
    ]
    return Segment(plan_version_id=1, start_date=PERIOD_START, end_date=end, items=items)


def _clock(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=_TZ)


def _order(rider_id: int, index: int, day: date, *, night: bool) -> SimpleNamespace:
    if night:
        order_time = _clock(day, 21, 40)
        deliver_time = _clock(day, 22, 18)
    else:
        order_time = _clock(day, 10, 0)
        deliver_time = _clock(day, 10, 28)
    return SimpleNamespace(
        id=rider_id * 1000 + index,
        order_no=f'B{rider_id}-{index}',
        site_id=SITE_ID,
        rider_id=rider_id,
        biz_date=day,
        distance_km=_MONEY('3.20'),
        weight_jin=_MONEY('4.50'),
        order_time=order_time,
        deliver_time=deliver_time,
        status=OrderStatus.completed.value,
        amount=_MONEY('28.00'),
    )


def _orders_for(rider_id: int) -> list[SimpleNamespace]:
    """每人 24 张，3 天每天 8 张，其中 4 张夜间。"""
    per_day = ORDERS_PER_RIDER // PERIOD_DAYS
    rows: list[SimpleNamespace] = []
    index = 1
    for offset in range(PERIOD_DAYS):
        day = PERIOD_START + timedelta(days=offset)
        for slot in range(per_day):
            rows.append(_order(rider_id, index, day, night=slot < 4))
            index += 1
    return rows


def _calc_input(rider_id: int, segment: Segment, covered: set[date]) -> CalcInput:
    return CalcInput(
        rider_id=rider_id,
        site_id=SITE_ID,
        period_start=PERIOD_START,
        period_end=PERIOD_START + timedelta(days=PERIOD_DAYS - 1),
        hire_date=date(2025, 1, 1),
        leave_date=None,
        employ_type='full_time',
        segments=[segment],
        orders=_orders_for(rider_id),
        day_flags={},
        employ_history=[],
        adjustments=[],
        advances=[],
        covered_dates=covered,
        site_order_dates=covered,
        persist_advance=False,
        period_id=1,
        rider_job_no=f'J{rider_id:03d}',
        rider_name=f'骑手{rider_id}',
    )


def _covered_days() -> set[date]:
    return {PERIOD_START + timedelta(days=offset) for offset in range(PERIOD_DAYS)}


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = list(rows)

    def unique(self) -> '_Rows':
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> '_Rows':
        return self


class _Stream:
    """逐条交出。调用方若先收成列表，第一行写入时计数已经到顶。"""

    def __init__(self, rows: list[Any], pulled: dict[str, int]) -> None:
        self._rows = rows
        self._index = 0
        self._pulled = pulled

    def scalars(self) -> '_Stream':
        return self

    def __aiter__(self) -> '_Stream':
        return self

    async def __anext__(self) -> Any:
        if self._index >= len(self._rows):
            raise StopAsyncIteration
        row = self._rows[self._index]
        self._index += 1
        self._pulled['n'] += 1
        return row


class _BenchDB:
    """记录语句并返回夹具。不连接数据库。"""

    def __init__(self, *, page_orders: list[Any], all_orders: list[Any]) -> None:
        self.page_orders = page_orders
        self.all_orders = all_orders
        self.statements: list[str] = []
        self.stream_calls = 0
        self.stream_options: dict[str, object] = {}
        self.pulled = {'n': 0}
        self.riders = [_rider_row(rider_id) for rider_id in range(1, RIDER_COUNT + 1)]
        self.site = _site_row()

    def _record(self, stmt: object) -> str:
        sql = _sql_of(stmt)
        self.statements.append(sql)
        return sql

    async def scalar(self, stmt: object) -> Any:
        sql = self._record(stmt)
        if 'count(' in sql:
            return len(self.all_orders)
        if 'rs_site' in sql:
            return self.site
        return None

    async def execute(self, stmt: object) -> _Rows:
        sql = self._record(stmt)
        if 'rs_order' in sql:
            return _Rows([(row,) for row in self.page_orders])
        if 'rs_payroll' in sql:
            return _Rows([(row,) for row in self.page_orders])
        return _Rows([])

    async def scalars(self, stmt: object) -> _Rows:
        sql = self._record(stmt)
        if 'rs_rider' in sql and 'rs_order' not in sql:
            return _Rows(self.riders)
        if 'rs_site' in sql:
            return _Rows([self.site])
        if 'distinct' in sql and 'rider_id' in sql and 'order_no' not in sql:
            return _Rows([rider.id for rider in self.riders])
        if 'rs_order' in sql:
            ids = {int(row.id) for row in self.page_orders}
            return _Rows([row for row in self.all_orders if int(row.id) in ids] or list(self.page_orders))
        return _Rows([])

    async def stream(self, stmt: object) -> _Stream:
        self.stream_calls += 1
        self.stream_options = stmt.get_execution_options()
        self._record(stmt)
        return _Stream(self.all_orders, self.pulled)

    def expunge(self, instance: object) -> None:
        return None


def _rider_row(rider_id: int) -> RiderSalaryRider:
    rider = RiderSalaryRider(
        job_no=f'J{rider_id:03d}',
        name=f'骑手{rider_id}',
        site_id=SITE_ID,
        hire_date=date(2025, 1, 1),
    )
    rider.id = rider_id
    return rider


def _site_row() -> RiderSalarySite:
    site = RiderSalarySite(code='BENCH', name='基准站')
    site.id = SITE_ID
    return site


def _order_row(rider_id: int, index: int) -> RiderSalaryOrder:
    day = PERIOD_START + timedelta(days=(index - 1) % PERIOD_DAYS)
    order = RiderSalaryOrder(
        order_no=f'L{rider_id}-{index}',
        site_id=SITE_ID,
        rider_id=rider_id,
        biz_date=day,
        distance_km=_MONEY('3.20'),
        weight_jin=_MONEY('4.50'),
        order_time=_clock(day, 10, 0),
        deliver_time=_clock(day, 10, 28),
        status=OrderStatus.completed.value,
        amount=_MONEY('28.00'),
    )
    order.id = rider_id * 1000 + index
    return order


def _list_orders(page_size: int) -> tuple[list[RiderSalaryOrder], list[RiderSalaryOrder]]:
    per_rider = ORDERS_PER_RIDER
    rows = [_order_row(rider_id, index) for rider_id in range(1, RIDER_COUNT + 1) for index in range(1, per_rider + 1)]
    return rows[:page_size], rows


def _print_line(text: str) -> None:
    print(text)


def _http_request() -> Request:
    return Request({
        'type': 'http',
        'asgi': {'version': '3.0'},
        'http_version': '1.1',
        'method': 'GET',
        'scheme': 'http',
        'path': '/api/v1/rider-salary/orders',
        'raw_path': b'/api/v1/rider-salary/orders',
        'query_string': b'page=1&size=20',
        'headers': [],
        'client': ('127.0.0.1', 1234),
        'server': ('testserver', 80),
    })


def test_calc_small_benchmark_stays_under_threshold() -> None:
    """2 名骑手、48 张订单的内存算薪中位数低于阈值，且三阶段都算出金额。"""
    segment = _benchmark_segment()
    covered = _covered_days()
    inputs = [_calc_input(rider_id, segment, covered) for rider_id in range(1, RIDER_COUNT + 1)]
    samples: list[float] = []
    last = None
    for _ in range(CALC_REPEATS):
        started = time.perf_counter()
        last = [run_calc_pipeline(data) for data in inputs]
        samples.append(time.perf_counter() - started)
    assert last is not None
    order_total = sum(len(data.orders) for data in inputs)
    for result, data in zip(last, inputs, strict=True):
        assert result.order_count == len(data.orders)
        assert result.valid_order_count == ORDERS_PER_RIDER
        assert result.per_order_total > 0
        assert result.daily_total > 0
        assert result.period_total > 0
        assert result.net > 0
        assert not any('求值失败' in item for item in result.warnings)
    median_ms = _median_ms(samples)
    per_sec = order_total / (median_ms / 1000)
    _print_line(
        f'P5-12 calc riders={RIDER_COUNT} orders={order_total} '
        f'repeats={CALC_REPEATS} median_ms={median_ms:.2f} orders_per_sec={per_sec:.1f}'
    )
    assert median_ms < CALC_MEDIAN_MS_MAX


def test_list_query_count_stays_flat() -> None:
    """订单列表和薪资单列表的语句数不随页内行数增加，且低于阈值。"""

    async def _order_page(page_size: int) -> tuple[int, float, int]:
        page_orders, all_orders = _list_orders(page_size)
        db = _BenchDB(page_orders=page_orders, all_orders=all_orders)
        started = time.perf_counter()
        with (
            set_page(_CustomPage),
            set_params(_CustomPageParams(page=1, size=page_size)),
            patch('fastapi_pagination.links.bases.request', _http_request),
            patch(
                'backend.plugin.rider_salary.service.order_service.get_visible_site_ids',
                AsyncMock(return_value=None),
            ),
        ):
            page = await order_service.get_list(
                db=db,
                request=SimpleNamespace(),
                site_id=SITE_ID,
                rider_id=None,
                date_from=PERIOD_START,
                date_to=PERIOD_START + timedelta(days=PERIOD_DAYS - 1),
                status=None,
                order_no=None,
                import_batch_id=None,
                is_locked=None,
            )
        elapsed = time.perf_counter() - started
        assert page['total'] == len(all_orders)
        assert len(page['items']) == page_size
        first = page['items'][0]
        job_no = first['rider_job_no'] if isinstance(first, dict) else first.rider_job_no
        assert job_no == 'J001'
        return len(db.statements), elapsed, page_size

    async def _payroll_page(page_size: int) -> tuple[int, float]:
        payrolls = [SimpleNamespace(id=index, rider_id=1, period_id=1) for index in range(1, page_size + 1)]
        db = _BenchDB(page_orders=payrolls, all_orders=payrolls)
        started = time.perf_counter()
        with (
            set_page(_CustomPage),
            set_params(_CustomPageParams(page=1, size=page_size)),
            patch('fastapi_pagination.links.bases.request', _http_request),
            patch(
                'backend.plugin.rider_salary.service.payroll_service.get_visible_site_ids',
                AsyncMock(return_value=None),
            ),
        ):
            page = await payroll_service.get_list(
                db,
                SimpleNamespace(),
                period_id=1,
                rider_id=None,
                site_id=None,
                kind=None,
                status=None,
                stale=None,
            )
        elapsed = time.perf_counter() - started
        assert page['total'] == page_size
        assert len(page['items']) == page_size
        return len(db.statements), elapsed

    async def _run() -> None:
        order_counts: list[int] = []
        order_elapsed: list[float] = []
        for page_size in LIST_PAGE_SIZES:
            count, elapsed, _size = await _order_page(page_size)
            order_counts.append(count)
            order_elapsed.append(elapsed)
        payroll_counts: list[int] = []
        payroll_elapsed: list[float] = []
        for page_size in LIST_PAGE_SIZES:
            count, elapsed = await _payroll_page(page_size)
            payroll_counts.append(count)
            payroll_elapsed.append(elapsed)
        order_ms = max(order_elapsed) * 1000
        payroll_ms = max(payroll_elapsed) * 1000
        _print_line(
            f'P5-12 list order_queries={order_counts} order_ms={order_ms:.2f} '
            f'payroll_queries={payroll_counts} payroll_ms={payroll_ms:.2f}'
        )
        assert order_counts[0] == order_counts[1]
        assert payroll_counts[0] == payroll_counts[1]
        assert order_counts[1] <= LIST_QUERY_MAX
        assert payroll_counts[1] <= LIST_QUERY_MAX
        assert order_counts[1] >= 2
        assert payroll_counts[1] >= 2
        assert order_ms < LIST_ELAPSED_MS_MAX
        assert payroll_ms < LIST_ELAPSED_MS_MAX

    anyio.run(_run)


def test_export_uses_stream_and_stays_under_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """订单导出走 write_only 流式写入；薪资明细迭代器同样逐行消费。"""
    flags: list[object] = []
    original_init = Workbook.__init__

    def _wrapped(self: Workbook, *args: object, **kwargs: object) -> None:
        flags.append(kwargs.get('write_only'))
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(Workbook, '__init__', _wrapped)
    original_append = WriteOnlyWorksheet.append

    async def _run() -> None:
        page_orders, all_orders = _list_orders(ORDERS_PER_RIDER)
        db = _BenchDB(page_orders=page_orders, all_orders=all_orders)
        pulled_at_append: list[int] = []

        def _spy_pulled(self: WriteOnlyWorksheet, row: object) -> None:
            pulled_at_append.append(db.pulled['n'])
            original_append(self, row)

        monkeypatch.setattr(WriteOnlyWorksheet, 'append', _spy_pulled)
        started = time.perf_counter()
        with (
            patch(
                'backend.plugin.rider_salary.service.order_service.get_visible_site_ids',
                AsyncMock(return_value=None),
            ),
            patch(
                'backend.plugin.rider_salary.service.order_service.audit_service.record',
                AsyncMock(),
            ),
        ):
            content, filename = await order_service.export(
                db=db,
                request=SimpleNamespace(),
                site_id=SITE_ID,
                date_from=PERIOD_START,
                date_to=PERIOD_START + timedelta(days=PERIOD_DAYS - 1),
                rider_id=None,
            )
        export_ms = (time.perf_counter() - started) * 1000
        assert content[:2] == b'PK'
        assert filename.startswith('订单明细_')
        assert db.stream_calls == 1
        assert db.stream_options.get('yield_per') == EXPORT_STREAM_YIELD
        assert flags[0] is True
        assert pulled_at_append[0] == 0
        assert pulled_at_append[1] == 1
        assert db.pulled['n'] == len(all_orders)
        assert pulled_at_append[1] < len(all_orders)

        detail_db = _BenchDB(page_orders=[], all_orders=_detail_pairs())
        book_started = time.perf_counter()
        book = StreamingWorkbook()
        sheet = book.add_sheet('明细', ['工号'])
        await append_streamed_rows(
            book,
            sheet,
            export_service._iter_detail_rows(
                detail_db,
                [1],
                {1: SimpleNamespace(job_no='J001', name='骑手1')},
                plan_names={1: '基准方案'},
                subject_names={1: '基础单价'},
            ),
        )
        detail_bytes = book.to_bytes()
        detail_ms = (time.perf_counter() - book_started) * 1000
        assert detail_bytes[:2] == b'PK'
        assert detail_db.stream_calls == 1
        assert detail_db.stream_options.get('yield_per') == EXPORT_STREAM_YIELD
        _print_line(
            f'P5-12 export orders={len(all_orders)} stream=yes write_only=yes '
            f'yield_per={EXPORT_STREAM_YIELD} export_ms={export_ms:.2f} '
            f'period_detail_stream=yes period_detail_ms={detail_ms:.2f}'
        )
        assert export_ms < EXPORT_ELAPSED_MS_MAX
        assert detail_ms < EXPORT_ELAPSED_MS_MAX

    anyio.run(_run)


def _detail_pairs() -> list[tuple[SimpleNamespace, str]]:
    rows: list[tuple[SimpleNamespace, str]] = []
    for index in range(1, ORDERS_PER_RIDER + 1):
        detail = SimpleNamespace(
            id=index,
            rider_id=1,
            payroll_id=1,
            biz_date=PERIOD_START,
            stage=CalcStage.per_order.value,
            plan_version_id=1,
            subject_id=1,
            order_id=index,
            amount=_MONEY('4.00'),
            include_in_gross=True,
            source=DetailSource.formula.value,
            calc_trace=None,
        )
        rows.append((detail, f'B1-{index}'))
    return rows

"""P5-04：列表、工作台导入缺口、启用版本下拉的查询次数不随行数增长。

用记录语句的假会话计数，不往共享库灌数据。
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Self
from unittest.mock import AsyncMock, patch

import anyio

from backend.plugin.rider_salary.enums import BindingType, EnableStatus, EntryGranularity
from backend.plugin.rider_salary.service.adjustment_service import AdjustmentService
from backend.plugin.rider_salary.service.dashboard_service import dashboard_service
from backend.plugin.rider_salary.service.plan_service import PlanService
from backend.plugin.rider_salary.service.rider_service import RiderService

_RIDER_SIZES = (3, 12)
_ADJUSTMENT_SIZES = (3, 12)
_SITE_COUNTS = (2, 20)
_PERIOD_HINT = '该科目按周期入账，业务日期仅用于展示，服务层不改动'
_TABLE_ORDER = (
    'rs_rider_plan_binding',
    'rs_plan_version',
    'rs_import_batch',
    'rs_adjustment',
    'rs_subject',
    'rs_order',
    'rs_site',
    'sys_user',
    'rs_plan',
    'rs_rider',
)


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


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = list(rows)

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> Self:
        return self


class _Session:
    """按表名返回夹具，并记下每条语句。不算真库。"""

    def __init__(self, tables: dict[str, list[Any]]) -> None:
        self.tables = tables
        self.statements: list[str] = []

    def _record(self, stmt: object) -> str:
        sql = _sql_of(stmt)
        self.statements.append(sql)
        return sql

    def _rows_for(self, sql: str) -> list[Any]:
        for name in _TABLE_ORDER:
            if name in sql:
                return list(self.tables.get(name, []))
        return []

    async def scalars(self, stmt: object) -> _Rows:
        return _Rows(self._rows_for(self._record(stmt)))

    async def execute(self, stmt: object, *_args: object, **_kwargs: object) -> _Rows:
        return _Rows(self._rows_for(self._record(stmt)))


def _hits(statements: list[str], table: str) -> list[str]:
    return [sql for sql in statements if table in sql]


def _rider(rider_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=rider_id,
        job_no=f'J{rider_id:03d}',
        name=f'骑手{rider_id}',
        phone=None,
        site_id=1 if rider_id % 2 else 2,
        employ_type='full_time',
        hire_date=date(2024, 1, 1),
        leave_date=None,
        status='on_job',
        advance_limit=None,
        settle_cycle_override=None,
        cycle_config_override=None,
        user_id=1000 + rider_id,
        remark=None,
        created_time=None,
        updated_time=None,
    )


def _binding(binding_id: int, rider_id: int, version_id: int, binding_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=binding_id,
        rider_id=rider_id,
        plan_version_id=version_id,
        binding_type=binding_type,
        start_date=date(2020, 1, 1),
        end_date=None,
    )


def _rider_tables() -> dict[str, list[Any]]:
    riders = [_rider(rider_id) for rider_id in range(1, _RIDER_SIZES[-1] + 1)]
    bindings = [_binding(rider_id, rider_id, 11, BindingType.default.value) for rider_id in range(1, len(riders) + 1)]
    bindings.append(_binding(100, 1, 12, BindingType.override.value))
    return {
        'rs_rider': riders,
        'rs_site': [
            SimpleNamespace(id=1, name='甲站'),
            SimpleNamespace(id=2, name='乙站'),
        ],
        'rs_rider_plan_binding': bindings,
        'rs_plan_version': [
            SimpleNamespace(id=11, plan_id=21),
            SimpleNamespace(id=12, plan_id=22),
        ],
        'rs_plan': [
            SimpleNamespace(id=21, short_name='默认方案', color='#111111'),
            SimpleNamespace(id=22, short_name='覆盖方案', color='#222222'),
        ],
        'sys_user': [
            SimpleNamespace(id=1000 + rider_id, status=0 if rider_id % 2 == 0 else 1)
            for rider_id in range(1, len(riders) + 1)
        ],
    }


def _adjustment(row_id: int, *, rider_id: int | None = None) -> SimpleNamespace:
    odd = row_id % 2 == 1
    return SimpleNamespace(
        id=row_id,
        rider_id=row_id if rider_id is None else rider_id,
        site_id=1,
        biz_date=date(2026, 10, row_id),
        subject_id=1 if odd else 2,
        amount=Decimal('12.50'),
        signed_amount=Decimal('12.50') if odd else Decimal('-12.50'),
        remark='迟到',
        is_locked=False,
        created_time=None,
        updated_time=None,
        period_id=None,
        operator_id=7,
    )


def _adjustment_tables() -> dict[str, list[Any]]:
    rows = [_adjustment(row_id) for row_id in range(1, _ADJUSTMENT_SIZES[-1] + 1)]
    rows[0] = _adjustment(1, rider_id=9999)
    return {
        'rs_adjustment': rows,
        'rs_rider': [
            SimpleNamespace(id=row_id, job_no=f'J{row_id:03d}', name=f'骑手{row_id}')
            for row_id in range(2, _ADJUSTMENT_SIZES[-1] + 1)
        ],
        'rs_subject': [
            SimpleNamespace(id=1, name='全勤奖', direction='bonus', entry_granularity=EntryGranularity.daily.value),
            SimpleNamespace(
                id=2, name='上期补差', direction='penalty', entry_granularity=EntryGranularity.period.value
            ),
        ],
    }


async def _listed(
    service: Any,
    session: _Session,
    paging_target: str,
    visible_target: str,
    size: int,
    **kwargs: Any,
) -> dict[str, Any]:
    def _paging(_db: object, _stmt: object, **_kwargs: object) -> dict[str, Any]:
        ids = list(range(size, 0, -1))
        return {'items': [{'id': pk} for pk in ids], 'total': size}

    with (
        patch(paging_target, AsyncMock(side_effect=_paging)),
        patch(visible_target, AsyncMock(return_value=None)),
    ):
        return await service.get_list(db=session, request=SimpleNamespace(), **kwargs)


def test_rider_list_queries_stay_flat() -> None:
    """分页从 3 行增到 12 行，补齐查询仍是固定次数，且覆盖方案优先。"""

    async def _run() -> None:
        counts: list[int] = []
        pages: list[dict[str, Any]] = []
        for size in _RIDER_SIZES:
            session = _Session(_rider_tables())
            page = await _listed(
                RiderService,
                session,
                'backend.plugin.rider_salary.service.rider_service.paging_data',
                'backend.plugin.rider_salary.service.rider_service.get_visible_site_ids',
                size,
                site_id=None,
                status=None,
                employ_type=None,
                keyword=None,
            )
            counts.append(len(session.statements))
            pages.append(page)
            assert _hits(session.statements, 'rs_rider_plan_binding')
            rider_sql = [sql for sql in session.statements if 'rs_rider' in sql and 'rs_rider_plan_binding' not in sql]
            assert len(rider_sql) == 1
            assert ' in ' in rider_sql[0]
            assert len(_hits(session.statements, 'rs_site')) == 1
            assert len(_hits(session.statements, 'sys_user')) == 1
            assert len(_hits(session.statements, 'rs_plan_version')) == 1
            plan_sql = [sql for sql in session.statements if 'rs_plan' in sql and 'rs_plan_version' not in sql]
            assert len(plan_sql) == 1
        assert counts[0] == counts[1]
        assert counts[1] <= 8
        assert counts[1] < 6 * _RIDER_SIZES[-1]
        small, large = pages
        assert [item['id'] for item in small['items']] == [3, 2, 1]
        assert [item['id'] for item in large['items']] == list(range(12, 0, -1))
        covered = next(item for item in large['items'] if item['id'] == 1)
        plain = next(item for item in large['items'] if item['id'] == 2)
        assert covered['plan_version_id'] == 12
        assert covered['plan_short_name'] == '覆盖方案'
        assert covered['plan_color'] == '#222222'
        assert covered['site_name'] == '甲站'
        assert covered['account_status'] == 1
        assert plain['plan_short_name'] == '默认方案'
        assert plain['site_name'] == '乙站'
        assert plain['account_status'] == 0

    anyio.run(_run)


def test_adjustment_list_queries_stay_flat() -> None:
    """分页从 3 行增到 12 行，奖惩补齐仍是 3 条批量查询。"""

    async def _run() -> None:
        counts: list[int] = []
        pages: list[dict[str, Any]] = []
        for size in _ADJUSTMENT_SIZES:
            session = _Session(_adjustment_tables())
            page = await _listed(
                AdjustmentService,
                session,
                'backend.plugin.rider_salary.service.adjustment_service.paging_data',
                'backend.plugin.rider_salary.service.adjustment_service.get_visible_site_ids',
                size,
                site_id=None,
                rider_id=None,
                subject_id=None,
                date_from=None,
                date_to=None,
                direction=None,
            )
            counts.append(len(session.statements))
            pages.append(page)
            assert len(_hits(session.statements, 'rs_adjustment')) == 1
            assert len(_hits(session.statements, 'rs_subject')) == 1
            rider_sql = [sql for sql in session.statements if 'rs_rider' in sql]
            assert len(rider_sql) == 1
            assert ' in ' in rider_sql[0]
            assert ' in ' in _hits(session.statements, 'rs_adjustment')[0]
        assert counts == [3, 3]
        small = pages[0]
        assert [item['id'] for item in small['items']] == [3, 2, 1]
        missing = next(item for item in small['items'] if item['id'] == 1)
        period_row = next(item for item in small['items'] if item['id'] == 2)
        daily_row = next(item for item in small['items'] if item['id'] == 3)
        assert missing['rider_name'] is None
        assert missing['rider_job_no'] is None
        assert missing['hint'] is None
        assert missing['subject_name'] == '全勤奖'
        assert period_row['rider_name'] == '骑手2'
        assert period_row['subject_name'] == '上期补差'
        assert period_row['direction'] == 'penalty'
        assert period_row['hint'] == _PERIOD_HINT
        assert period_row['signed_amount'] == Decimal('-12.50')
        assert daily_row['hint'] is None
        assert daily_row['rider_job_no'] == 'J003'

    anyio.run(_run)


def test_import_gap_queries_stay_flat() -> None:
    """站点数从 2 增到 20，导入缺口仍是站点、批次、订单日期各 1 次查询。"""

    async def _run() -> None:
        start = date(2026, 10, 1)
        today = date(2026, 10, 2)
        counts: list[int] = []
        for count in _SITE_COUNTS:
            sites = [SimpleNamespace(id=site_id, name=f'站{site_id}') for site_id in range(1, count + 1)]
            session = _Session({'rs_site': sites, 'rs_import_batch': [], 'rs_order': []})
            block = await dashboard_service._import_gaps(session, None, start, start, today)
            counts.append(len(session.statements))
            assert block is not None
            assert block.count == count
            assert len(block.items) == min(10, count)
            assert block.items[0] == {'site_id': 1, 'site_name': '站1', 'date': '2026-10-01'}
            assert len(_hits(session.statements, 'rs_site')) == 1
            batch_sql = _hits(session.statements, 'rs_import_batch')
            order_sql = _hits(session.statements, 'rs_order')
            assert len(batch_sql) == 1
            assert len(order_sql) == 1
            assert 'site_id in' in batch_sql[0]
            assert 'group by' in order_sql[0]
            assert 'site_id =' not in order_sql[0]
        assert counts == [3, 3]

        sites = [SimpleNamespace(id=1, name='甲站'), SimpleNamespace(id=2, name='乙站')]
        batches = [
            SimpleNamespace(site_id=1, date_from=date(2026, 10, 1), date_to=date(2026, 10, 1)),
            SimpleNamespace(site_id=1, date_from=None, date_to=date(2026, 10, 3)),
            SimpleNamespace(site_id=2, date_from=date(2026, 11, 1), date_to=date(2026, 11, 2)),
        ]
        orders = [(1, date(2026, 10, 2)), (1, None)]
        session = _Session({'rs_site': sites, 'rs_import_batch': batches, 'rs_order': orders})
        block = await dashboard_service._import_gaps(session, {1, 2}, start, date(2026, 10, 31), date(2026, 10, 4))
        assert block is not None
        assert block.count == 4
        assert block.items == [
            {'site_id': 1, 'site_name': '甲站', 'date': '2026-10-03'},
            {'site_id': 2, 'site_name': '乙站', 'date': '2026-10-01'},
            {'site_id': 2, 'site_name': '乙站', 'date': '2026-10-02'},
            {'site_id': 2, 'site_name': '乙站', 'date': '2026-10-03'},
        ]
        assert len(session.statements) == 3

        empty = _Session({'rs_site': [], 'rs_import_batch': [], 'rs_order': []})
        assert await dashboard_service._import_gaps(empty, None, start, start, today) is None
        assert len(empty.statements) == 1

    anyio.run(_run)


def _active_versions(size: int) -> list[SimpleNamespace]:
    """id 从大到小。方案 1 启用，方案 2 停用，方案 3 视为已删除。"""
    return [
        SimpleNamespace(id=size - offset, plan_id=(offset % 3) + 1, version_no=offset + 1) for offset in range(size)
    ]


def test_active_dropdown_queries_stay_flat() -> None:
    """启用版本从 3 个增到 15 个，方案仍是 1 次 IN 查询；停用和缺失方案不进下拉。"""

    async def _run() -> None:
        plans = [
            SimpleNamespace(id=1, name='纯按单', short_name='按单', color='#111111', status=EnableStatus.enable.value),
            SimpleNamespace(id=2, name='停用方案', short_name='停', color='#000000', status=EnableStatus.disable.value),
        ]
        counts: list[int] = []
        for size in (3, 15):
            versions = _active_versions(size)
            session = _Session({'rs_plan_version': versions, 'rs_plan': plans})
            result = await PlanService.get_active_dropdown(session)
            counts.append(len(session.statements))
            version_sql = _hits(session.statements, 'rs_plan_version')
            plan_sql = [sql for sql in session.statements if 'rs_plan' in sql and 'rs_plan_version' not in sql]
            assert len(version_sql) == 1
            assert len(plan_sql) == 1
            assert ' in ' in plan_sql[0]
            kept = [item for item in versions if item.plan_id == 1]
            assert [item.id for item in result] == [item.id for item in kept]
            assert result[0].plan_name == '纯按单'
            assert result[0].short_name == '按单'
            assert result[0].color == '#111111'
            assert result[0].version_no == kept[0].version_no
            assert all(item.plan_name != '停用方案' for item in result)
        assert counts == [2, 2]
        assert counts[1] < 1 + 15

        empty = _Session({'rs_plan_version': [], 'rs_plan': plans})
        assert await PlanService.get_active_dropdown(empty) == []
        assert len(empty.statements) == 1
        assert _hits(empty.statements, 'rs_plan_version')
        assert not [sql for sql in empty.statements if 'rs_plan' in sql and 'rs_plan_version' not in sql]

    anyio.run(_run)

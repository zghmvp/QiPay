"""P5-10：试算超限检查用 count，不把订单 id 拉进内存。"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.service import calc_service
from backend.plugin.rider_salary.service.calc_service import trial_max_orders, trial_rider_range

START = date(2026, 9, 1)
END = date(2026, 9, 30)


def _rider() -> SimpleNamespace:
    return SimpleNamespace(id=7, site_id=3, deleted=0)


def _is_order_count(stmt: object) -> bool:
    sql = str(stmt.compile()).lower()  # type: ignore[attr-defined]
    return 'count(' in sql and 'rs_order' in sql


def _count_sql(stmt: object) -> str:
    return str(stmt.compile(compile_kwargs={'literal_binds': True}))  # type: ignore[attr-defined]


class _Session:
    """按语句分流：骑手查询返回骑手，订单计数返回给定数量。"""

    def __init__(self, order_count: int | None) -> None:
        self.order_count = order_count
        self.statements: list[object] = []
        self.scalars = AsyncMock(side_effect=AssertionError('试算超限检查不应拉取订单 id'))

    async def scalar(self, stmt: object) -> object:
        self.statements.append(stmt)
        if _is_order_count(stmt):
            return self.order_count
        return _rider()


def _count_statements(db: _Session) -> list[object]:
    return [stmt for stmt in db.statements if _is_order_count(stmt)]


def test_trial_over_limit_uses_count_and_skips_pipeline() -> None:
    """订单数超过上限时返回 400，且计数语句是 count(*)，不进入算薪。"""

    async def _run() -> None:
        limit = trial_max_orders()
        db = _Session(limit + 1)
        load = AsyncMock(side_effect=AssertionError('超限后不应加载算薪输入'))
        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(calc_service, '_load_calc_input', load)
            with pytest.raises(errors.RequestError, match=f'试算订单数超过上限 {limit}'):
                await trial_rider_range(
                    db,  # type: ignore[arg-type]
                    rider_id=7,
                    start=START,
                    end=END,
                    forced_plan_version=SimpleNamespace(id=1),  # type: ignore[arg-type]
                )
        counts = _count_statements(db)
        assert len(counts) == 1
        sql = _count_sql(counts[0]).lower()
        select_clause = sql.split(' from ', 1)[0]
        assert 'count(' in select_clause
        assert '.id' not in select_clause
        assert 'rs_order.rider_id = 7' in sql
        assert 'rs_order.site_id = 3' in sql
        assert "rs_order.biz_date >= '2026-09-01'" in sql
        assert "rs_order.biz_date <= '2026-09-30'" in sql
        assert 'rs_order.deleted = 0' in sql
        load.assert_not_called()
        db.scalars.assert_not_called()

    anyio.run(_run)


def test_trial_at_limit_continues_without_loading_ids() -> None:
    """订单数等于上限时继续试算，计数仍走 count，且不调用 scalars。"""

    async def _run() -> None:
        limit = trial_max_orders()
        db = _Session(limit)
        loaded = SimpleNamespace(name='input')
        expected = SimpleNamespace(net='ok')
        load = AsyncMock(return_value=loaded)
        pipeline = MagicMock(return_value=expected)
        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(calc_service, '_load_calc_input', load)
            patcher.setattr(calc_service, 'run_calc_pipeline', pipeline)
            result = await trial_rider_range(
                db,  # type: ignore[arg-type]
                rider_id=7,
                start=START,
                end=END,
                forced_plan_version=SimpleNamespace(id=11),  # type: ignore[arg-type]
            )
        assert result is expected
        assert len(_count_statements(db)) == 1
        load.assert_awaited_once()
        assert load.await_args.kwargs['persist_advance'] is False
        assert load.await_args.kwargs['rider'].id == 7
        period = load.await_args.kwargs['period']
        assert period.start_date == START
        assert period.end_date == END
        pipeline.assert_called_once_with(loaded)
        db.scalars.assert_not_called()

    anyio.run(_run)


def test_trial_null_count_treated_as_zero() -> None:
    """计数结果为空时按 0 单继续，不因空值误判超限。"""

    async def _run() -> None:
        db = _Session(None)
        load = AsyncMock(return_value=SimpleNamespace())
        pipeline = MagicMock(return_value=SimpleNamespace())
        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(calc_service, '_load_calc_input', load)
            patcher.setattr(calc_service, 'run_calc_pipeline', pipeline)
            await trial_rider_range(
                db,  # type: ignore[arg-type]
                rider_id=7,
                start=START,
                end=END,
                forced_plan_version=SimpleNamespace(id=1),  # type: ignore[arg-type]
            )
        load.assert_awaited_once()
        db.scalars.assert_not_called()

    anyio.run(_run)

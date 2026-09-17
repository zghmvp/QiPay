"""插件内轻量重算任务（BackgroundTasks，非 Celery）"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from backend.common.exception import errors
from backend.database.db import async_db_session
from backend.plugin.rider_salary.crud.recalc_job import recalc_job_dao
from backend.plugin.rider_salary.enums import PeriodStatus, RecalcJobSource, RecalcJobStatus
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.recalc_job import RiderSalaryRecalcJob
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.model.site import RiderSalarySite
from backend.plugin.rider_salary.schema.recalc_job import (
    BatchRecalcStaleParam,
    BatchRecalcStalePreview,
    BatchRecalcStaleResult,
    GetRecalcJobDetail,
)
from backend.plugin.rider_salary.service.calendar_service import parse_month, period_range_text
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.utils.timezone import timezone

if TYPE_CHECKING:
    from fastapi import BackgroundTasks, Request
    from sqlalchemy.ext.asyncio import AsyncSession


def _job_detail(row: RiderSalaryRecalcJob) -> GetRecalcJobDetail:
    return GetRecalcJobDetail.model_validate(row)


class RecalcJobService:
    """重算任务"""

    async def get(self, *, db: AsyncSession, request: Request, pk: int) -> GetRecalcJobDetail:
        row = await recalc_job_dao.get_or_404(db, pk)
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, row.site_id)
        return _job_detail(row)

    async def create_import_job(
        self,
        db: AsyncSession,
        *,
        site_id: int,
        batch_id: int,
        rider_ids: list[int],
        date_from: date,
        date_to: date,
        operator_id: int,
    ) -> RiderSalaryRecalcJob:
        """创建导入后重算任务（排队中）"""
        periods = await _open_periods_overlapping(db, site_id=site_id, date_from=date_from, date_to=date_to)
        row = RiderSalaryRecalcJob(
            site_id=site_id,
            source=RecalcJobSource.import_batch.value,
            source_id=batch_id,
            status=RecalcJobStatus.queued.value,
            message='排队中，等待后台重算',
            total_periods=len(periods),
            done_periods=0,
            rider_count=len(set(rider_ids)),
            operator_id=operator_id,
            payload={
                'rider_ids': list(rider_ids),
                'date_from': date_from.isoformat(),
                'date_to': date_to.isoformat(),
                'period_ids': [p.id for p in periods],
            },
        )
        return await recalc_job_dao.create(db, row)

    async def preview_stale_batch(
        self,
        *,
        db: AsyncSession,
        request: Request,
        obj: BatchRecalcStaleParam,
    ) -> BatchRecalcStalePreview:
        site, month_key, rows = await self._load_stale_targets(db=db, request=request, obj=obj)
        rider_ids: set[int] = set()
        ranges: list[str] = []
        for period, cnt, stale_riders in rows:
            ranges.append(f'{period_range_text(period.start_date, period.end_date)}（{int(cnt)} 人）')
            rider_ids.update(stale_riders)
        return BatchRecalcStalePreview(
            site_id=site.id,
            site_name=site.name,
            month=month_key,
            period_count=len(rows),
            stale_rider_count=len(rider_ids),
            period_ranges=ranges[:20],
        )

    async def submit_stale_batch(
        self,
        *,
        db: AsyncSession,
        request: Request,
        obj: BatchRecalcStaleParam,
        background_tasks: BackgroundTasks,
    ) -> BatchRecalcStaleResult:
        site, month_key, rows = await self._load_stale_targets(db=db, request=request, obj=obj)
        if not rows:
            raise errors.RequestError(msg='本站本月暂无需要重算的周期')
        rider_ids: set[int] = set()
        period_ids: list[int] = []
        for period, _cnt, stale_riders in rows:
            period_ids.append(period.id)
            rider_ids.update(stale_riders)
        operator_id = int(getattr(request.user, 'id', 0) or 0)
        job = RiderSalaryRecalcJob(
            site_id=site.id,
            source=RecalcJobSource.stale_batch.value,
            source_id=None,
            status=RecalcJobStatus.queued.value,
            message=f'排队中：将重算 {site.name} {month_key} 共 {len(period_ids)} 个周期',
            month=month_key,
            total_periods=len(period_ids),
            done_periods=0,
            rider_count=len(rider_ids),
            operator_id=operator_id,
            payload={'period_ids': period_ids, 'rider_ids': list(rider_ids)},
        )
        job = await recalc_job_dao.create(db, job)
        await db.commit()
        background_tasks.add_task(run_recalc_job, job_id=job.id)
        return BatchRecalcStaleResult(
            job_id=job.id,
            site_name=site.name,
            period_count=len(period_ids),
            rider_count=len(rider_ids),
            queued=True,
            message=f'已提交「{site.name}」{month_key} 批量重算（{len(period_ids)} 个周期 / {len(rider_ids)} 名骑手）',
        )

    async def retry(
        self,
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        background_tasks: BackgroundTasks,
    ) -> GetRecalcJobDetail:
        row = await recalc_job_dao.get_or_404(db, pk)
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, row.site_id)
        if row.status != RecalcJobStatus.failed.value:
            raise errors.RequestError(msg='仅失败任务可重试')
        row.status = RecalcJobStatus.queued.value
        row.message = '已重新排队'
        row.done_periods = 0
        row.started_time = None
        row.finished_time = None
        await db.flush()
        await db.commit()
        background_tasks.add_task(run_recalc_job, job_id=row.id)
        return _job_detail(row)

    async def _load_stale_targets(
        self,
        *,
        db: AsyncSession,
        request: Request,
        obj: BatchRecalcStaleParam,
    ) -> tuple[RiderSalarySite, str, list[tuple[RiderSalarySettlePeriod, int, list[int]]]]:
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, obj.site_id)
        site = await db.get(RiderSalarySite, obj.site_id)
        if site is None or getattr(site, 'deleted', 0):
            raise errors.NotFoundError(msg='站点不存在')
        month_key, start, end = parse_month(obj.month, timezone.now().date())
        stmt = (
            select(RiderSalarySettlePeriod, RiderSalaryPayroll.rider_id)
            .join(RiderSalaryPayroll, RiderSalaryPayroll.period_id == RiderSalarySettlePeriod.id)
            .where(
                RiderSalaryPayroll.stale.is_(True),
                RiderSalaryPayroll.deleted == 0,
                RiderSalarySettlePeriod.deleted == 0,
                RiderSalarySettlePeriod.site_id == obj.site_id,
                RiderSalarySettlePeriod.start_date <= end,
                RiderSalarySettlePeriod.end_date >= start,
                RiderSalarySettlePeriod.status.in_([PeriodStatus.open.value, PeriodStatus.reopened.value]),
            )
        )
        raw = (await db.execute(stmt)).all()
        by_period: dict[int, tuple[RiderSalarySettlePeriod, set[int]]] = {}
        for period, rider_id in raw:
            entry = by_period.get(period.id)
            if entry is None:
                by_period[period.id] = (period, {int(rider_id)})
            else:
                entry[1].add(int(rider_id))
        rows = [(period, len(riders), sorted(riders)) for period, riders in by_period.values()]
        rows.sort(key=lambda item: item[0].end_date)
        return site, month_key, rows


async def _open_periods_overlapping(
    db: AsyncSession,
    *,
    site_id: int,
    date_from: date,
    date_to: date,
) -> list[RiderSalarySettlePeriod]:
    return list(
        (
            await db.scalars(
                select(RiderSalarySettlePeriod).where(
                    RiderSalarySettlePeriod.site_id == site_id,
                    RiderSalarySettlePeriod.status.in_([PeriodStatus.open.value, PeriodStatus.reopened.value]),
                    RiderSalarySettlePeriod.start_date <= date_to,
                    RiderSalarySettlePeriod.end_date >= date_from,
                    RiderSalarySettlePeriod.deleted == 0,
                )
            )
        ).all()
    )


async def run_recalc_job(*, job_id: int) -> None:
    """后台执行重算任务并回写状态。"""
    from backend.common.log import log
    from backend.plugin.rider_salary.service.calc_service import calculate_period

    try:
        async with async_db_session.begin() as db:
            job = await recalc_job_dao.get(db, job_id)
            if job is None:
                return
            job.status = RecalcJobStatus.running.value
            job.message = '计算中'
            job.started_time = timezone.now()
            job.done_periods = 0
            await db.flush()

            payload: dict[str, Any] = job.payload or {}
            period_ids = [int(x) for x in (payload.get('period_ids') or [])]
            rider_ids_raw = payload.get('rider_ids')
            rider_ids = [int(x) for x in rider_ids_raw] if rider_ids_raw else None

            if not period_ids and job.source == RecalcJobSource.import_batch.value:
                date_from = date.fromisoformat(str(payload['date_from']))
                date_to = date.fromisoformat(str(payload['date_to']))
                periods = await _open_periods_overlapping(db, site_id=job.site_id, date_from=date_from, date_to=date_to)
                period_ids = [p.id for p in periods]
                job.total_periods = len(period_ids)

            done = 0
            for pid in period_ids:
                await calculate_period(db, period_id=pid, rider_ids=rider_ids, operator=None)
                done += 1
                job.done_periods = done
                await db.flush()

            job.status = RecalcJobStatus.done.value
            job.message = f'完成：已重算 {done} 个周期'
            job.finished_time = timezone.now()
    except Exception as exc:
        log.exception('重算任务失败 job_id=%s', job_id)
        try:
            async with async_db_session.begin() as db:
                job = await recalc_job_dao.get(db, job_id)
                if job is not None:
                    job.status = RecalcJobStatus.failed.value
                    job.message = f'失败：{exc}'
                    job.finished_time = timezone.now()
        except Exception:
            log.exception('回写重算失败状态异常 job_id=%s', job_id)


recalc_job_service = RecalcJobService()

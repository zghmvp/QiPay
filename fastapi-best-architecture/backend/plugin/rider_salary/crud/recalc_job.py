from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.rider_salary.model.recalc_job import RiderSalaryRecalcJob


def latest_recalc_job_select(*, site_id: int, source: str | None = None) -> Select:
    """本站最近一条重算任务（按 id 倒序）。"""
    stmt = select(RiderSalaryRecalcJob).where(
        RiderSalaryRecalcJob.site_id == site_id,
        RiderSalaryRecalcJob.deleted == 0,
    )
    if source:
        stmt = stmt.where(RiderSalaryRecalcJob.source == source)
    return stmt.order_by(RiderSalaryRecalcJob.id.desc()).limit(1)


class CRUDRecalcJob:
    """重算任务"""

    async def get(self, db: AsyncSession, pk: int) -> RiderSalaryRecalcJob | None:
        return await db.get(RiderSalaryRecalcJob, pk)

    async def get_or_404(self, db: AsyncSession, pk: int) -> RiderSalaryRecalcJob:
        row = await self.get(db, pk)
        if row is None or getattr(row, 'deleted', 0):
            raise errors.NotFoundError(msg='重算任务不存在')
        return row

    async def create(self, db: AsyncSession, row: RiderSalaryRecalcJob) -> RiderSalaryRecalcJob:
        db.add(row)
        await db.flush()
        await db.refresh(row)
        return row

    async def get_latest_by_site(
        self,
        db: AsyncSession,
        *,
        site_id: int,
        source: str | None = None,
    ) -> RiderSalaryRecalcJob | None:
        stmt = latest_recalc_job_select(site_id=site_id, source=source)
        return await db.scalar(stmt)

    async def list_by_source(
        self,
        db: AsyncSession,
        *,
        source: str,
        source_id: int,
    ) -> list[RiderSalaryRecalcJob]:
        stmt = (
            select(RiderSalaryRecalcJob)
            .where(
                RiderSalaryRecalcJob.source == source,
                RiderSalaryRecalcJob.source_id == source_id,
                RiderSalaryRecalcJob.deleted == 0,
            )
            .order_by(RiderSalaryRecalcJob.id.desc())
        )
        return list((await db.scalars(stmt)).all())


recalc_job_dao = CRUDRecalcJob()

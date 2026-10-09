"""算薪作业：落库进度，按批提交，单个骑手失败不影响同批其他人。"""

import asyncio

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from fastapi import Request
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.database.db import async_db_session
from backend.plugin.rider_salary.enums import CalcJobStatus
from backend.plugin.rider_salary.model.calc_job import RiderSalaryCalcJob
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.schema.calc_job import CalcJobFailure, GetCalcJobDetail
from backend.plugin.rider_salary.service import calc_service
from backend.plugin.rider_salary.service.calc_service import (
    PERIOD_CALCULATING_LOCK_MSG,
    CalcPersistSkippedError,
    CalcResult,
    append_period_calc_warning,
    load_site_period_coverage,
    read_period_for_calc,
    record_rider_skips,
    riders_for_period,
)
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.utils.timezone import timezone

CALC_JOB_BATCH_SIZE = 20
_ACTIVE = (CalcJobStatus.queued.value, CalcJobStatus.running.value)
_TERMINAL = (CalcJobStatus.succeeded.value, CalcJobStatus.failed.value, CalcJobStatus.partial.value)
_PENDING: set[asyncio.Task[None]] = set()
_ACTIVE_INDEX = 'uq_rs_calc_job_one_active'


@dataclass
class CalcEnqueueResult:
    """一次触发算薪的返回。"""

    job_id: int
    queued: bool
    calculated: int
    warnings: list[str]


def resolve_calc_job_status(
    *,
    success_count: int,
    failed_count: int,
    skipped: bool,
    crashed: bool = False,
) -> str:
    """根据成功、失败和跳过决定作业终态。

    :param success_count: 成功骑手数
    :param failed_count: 失败骑手数
    :param skipped: 是否有人因周期不可写被跳过
    :param crashed: 作业级中断。已有成功时记为部分成功
    :return: 状态值
    """
    if success_count and (failed_count or crashed):
        return CalcJobStatus.partial.value
    if not success_count and (failed_count or skipped or crashed):
        return CalcJobStatus.failed.value
    return CalcJobStatus.succeeded.value


def session_joins_external(db: AsyncSession) -> bool:
    """当前会话是否嵌在外部事务里（集成测试的保存点）。

    :param db: 数据库会话
    :return: 嵌在外部事务中则为真
    """
    sync = db.sync_session
    transaction = sync.get_transaction()
    if transaction is not None and transaction.parent is not None:
        return True
    if not sync.in_transaction():
        return False
    return bool(sync.connection().in_nested_transaction())


async def period_has_active_job(db: AsyncSession, period_id: int) -> bool:
    """周期是否有排队中或计算中的作业。

    :param db: 数据库会话
    :param period_id: 结算周期 ID
    :return: 有活动作业则为真
    """
    count = await db.scalar(
        select(func.count())
        .select_from(RiderSalaryCalcJob)
        .where(
            RiderSalaryCalcJob.period_id == period_id,
            RiderSalaryCalcJob.status.in_(_ACTIVE),
            RiderSalaryCalcJob.deleted == 0,
        )
    )
    return int(count or 0) > 0


async def wait_pending_calc_jobs() -> None:
    """等本进程里已登记的算薪任务结束。供提交后改走连接池的测试使用。"""
    pending = [task for task in list(_PENDING) if not task.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def schedule_after_commit(db: AsyncSession, starter: Callable[[], Awaitable[None]]) -> None:
    """事务真正提交后再启动协程。回滚不会启动。

    :param db: 数据库会话
    :param starter: 返回协程的函数，提交时才调用
    """
    sync = db.sync_session

    def _on_commit(_session: object) -> None:
        task = asyncio.get_running_loop().create_task(starter())
        _PENDING.add(task)
        task.add_done_callback(_PENDING.discard)

    event.listen(sync, 'after_commit', _on_commit, once=True)


async def enqueue_period_calc(
    db: AsyncSession,
    *,
    period: RiderSalarySettlePeriod,
    rider_ids: list[int] | None,
    operator: Request | None,
) -> CalcEnqueueResult:
    """写入作业。嵌套事务里当场算完；根事务提交后再后台分批算。

    :param db: 数据库会话
    :param period: 结算周期
    :param rider_ids: 指定骑手，空表示周期内全部
    :param operator: 操作人
    :return: 作业号、是否仍在后台、已成功人数和告警
    """
    targets = await riders_for_period(db, period, rider_ids)
    job = await _insert_job(
        db,
        period=period,
        rider_ids=rider_ids,
        total_count=len(targets),
        operator=operator,
    )
    if session_joins_external(db):
        await _execute_job_on_session(db, job, operator)
        await db.refresh(job)
        return CalcEnqueueResult(
            job_id=job.id,
            queued=False,
            calculated=int(job.success_count or 0),
            warnings=list(job.warnings or []),
        )
    job_id = job.id
    schedule_after_commit(db, lambda: run_calc_job(job_id))
    return CalcEnqueueResult(job_id=job_id, queued=True, calculated=0, warnings=[])


async def run_period_calc_in_session(
    db: AsyncSession,
    *,
    period_id: int,
    rider_ids: list[int] | None,
    operator: Request | None,
) -> CalcEnqueueResult:
    """在调用方会话里创建并执行作业。锁账后的补算走这里。

    :param db: 数据库会话
    :param period_id: 结算周期 ID
    :param rider_ids: 指定骑手
    :param operator: 操作人
    :return: 作业结果
    """
    period = await _load_period(db, period_id)
    return await enqueue_period_calc(db, period=period, rider_ids=rider_ids, operator=operator)


async def run_calc_job(job_id: int) -> None:
    """独立事务执行已提交的作业。每 20 名骑手提交一次。

    :param job_id: 作业 ID
    """
    from backend.common.log import log

    try:
        rider_ids = await _claim_job(job_id)
        if rider_ids is None:
            return
        outcomes: list[Any] = []
        for offset in range(0, len(rider_ids), CALC_JOB_BATCH_SIZE):
            outcomes.extend(await _commit_batch(job_id, rider_ids[offset : offset + CALC_JOB_BATCH_SIZE]))
        await _finalize_job(job_id, outcomes)
    except Exception as exc:
        log.exception('算薪作业失败 job_id=%s', job_id)
        await _mark_job_crashed(job_id, str(exc))


async def schedule_import_recalc(
    db: AsyncSession,
    *,
    site_id: int,
    rider_ids: list[int],
    date_from: date,
    date_to: date,
    operator_id: int,
) -> None:
    """导入事务提交后再重算。嵌套事务里改在当前会话执行，避免提前提交。

    :param db: 数据库会话
    :param site_id: 站点 ID
    :param rider_ids: 本次导入的骑手
    :param date_from: 业务日起
    :param date_to: 业务日止
    :param operator_id: 操作人 ID
    """
    from backend.plugin.rider_salary.service.import_service import recalc_imported_periods, recalc_imported_periods_on

    if session_joins_external(db):
        await recalc_imported_periods_on(
            db,
            site_id=site_id,
            rider_ids=rider_ids,
            date_from=date_from,
            date_to=date_to,
            operator_id=operator_id,
        )
        return
    schedule_after_commit(
        db,
        lambda: recalc_imported_periods(
            site_id=site_id,
            rider_ids=list(rider_ids),
            date_from=date_from,
            date_to=date_to,
            operator_id=operator_id,
        ),
    )


async def get_visible_calc_job(*, db: AsyncSession, request: Request, job_id: int) -> GetCalcJobDetail:
    """按站点可见范围读取作业。

    :param db: 数据库会话
    :param request: 请求对象
    :param job_id: 作业 ID
    :return: 作业详情
    """
    job = await db.get(RiderSalaryCalcJob, job_id)
    if job is None or job.deleted:
        raise errors.NotFoundError(msg='算薪作业不存在')
    visible = await get_visible_site_ids(request, db)
    assert_site_visible(visible, job.site_id)
    return _to_detail(job)


def _to_detail(job: RiderSalaryCalcJob) -> GetCalcJobDetail:
    try:
        label = CalcJobStatus(job.status).label
    except ValueError:
        label = job.status
    failures: list[CalcJobFailure] = []
    for row in job.failures or []:
        if not isinstance(row, dict):
            continue
        failures.append(
            CalcJobFailure(
                rider_id=int(row.get('rider_id') or 0),
                job_no=str(row.get('job_no') or ''),
                reason=str(row.get('reason') or ''),
            )
        )
    return GetCalcJobDetail(
        id=job.id,
        period_id=job.period_id,
        site_id=job.site_id,
        status=job.status,
        status_label=label,
        total_count=int(job.total_count or 0),
        done_count=int(job.done_count or 0),
        success_count=int(job.success_count or 0),
        failed_count=int(job.failed_count or 0),
        failures=failures,
        warnings=[str(item) for item in (job.warnings or []) if str(item)],
        error_message=job.error_message,
        started_time=job.started_time,
        finished_time=job.finished_time,
    )


async def _insert_job(
    db: AsyncSession,
    *,
    period: RiderSalarySettlePeriod,
    rider_ids: list[int] | None,
    total_count: int,
    operator: Request | None,
) -> RiderSalaryCalcJob:
    if await period_has_active_job(db, period.id):
        raise errors.ConflictError(msg=PERIOD_CALCULATING_LOCK_MSG)
    job = RiderSalaryCalcJob(
        period_id=period.id,
        site_id=period.site_id,
        total_count=total_count,
        operator_id=_operator_id(operator),
        target_rider_ids=list(rider_ids) if rider_ids is not None else None,
        status=CalcJobStatus.queued.value,
    )
    try:
        async with db.begin_nested():
            db.add(job)
            await db.flush()
    except IntegrityError as exc:
        if _is_active_job_conflict(exc):
            raise errors.ConflictError(msg=PERIOD_CALCULATING_LOCK_MSG) from exc
        raise
    return job


async def _execute_job_on_session(db: AsyncSession, job: RiderSalaryCalcJob, operator: Request | None) -> None:
    period = await _load_period(db, job.period_id)
    if await _abort_closed_period(db, job, period):
        return
    job.status = CalcJobStatus.running.value
    job.started_time = timezone.now()
    targets = await riders_for_period(db, period, _target_ids(job))
    job.total_count = len(targets)
    await db.flush()
    outcomes = await _settle_riders(db, job, period, targets, operator)
    await _publish_outcomes(period.id, outcomes)
    _apply_terminal(job, skipped=_has_skip(outcomes))
    await db.flush()


async def _claim_job(job_id: int) -> list[int] | None:
    async with async_db_session.begin() as db:
        job = await _lock_job(db, job_id)
        if job is None or job.status != CalcJobStatus.queued.value:
            return None
        period = await _load_period(db, job.period_id)
        if await _abort_closed_period(db, job, period):
            return None
        targets = await riders_for_period(db, period, _target_ids(job))
        job.status = CalcJobStatus.running.value
        job.started_time = timezone.now()
        job.total_count = len(targets)
        return list(targets)


async def _commit_batch(job_id: int, rider_ids: list[int]) -> list[Any]:
    async with async_db_session.begin() as db:
        job = await _lock_job(db, job_id)
        if job is None or job.status != CalcJobStatus.running.value:
            return []
        period = await _load_period(db, job.period_id)
        return await _settle_riders(db, job, period, rider_ids, None)


async def _finalize_job(job_id: int, outcomes: list[Any]) -> None:
    async with async_db_session.begin() as db:
        job = await _lock_job(db, job_id)
        if job is None or job.status in _TERMINAL:
            return
        await _publish_outcomes(job.period_id, outcomes)
        _apply_terminal(job, skipped=_has_skip(outcomes))


async def _mark_job_crashed(job_id: int, message: str) -> None:
    try:
        async with async_db_session.begin() as db:
            job = await _lock_job(db, job_id)
            if job is None or job.status in _TERMINAL:
                return
            job.error_message = _failure_reason(message)
            _apply_terminal(job, skipped=True, crashed=True)
            await append_period_calc_warning(job.period_id, f'后台算薪失败：{job.error_message}')
    except Exception:
        from backend.common.log import log

        log.exception('回写算薪作业失败状态失败 job_id=%s', job_id)


async def _settle_riders(
    db: AsyncSession,
    job: RiderSalaryCalcJob,
    period: RiderSalarySettlePeriod,
    rider_ids: list[int],
    operator: Request | None,
) -> list[Any]:
    coverage = None
    if rider_ids:
        coverage = await load_site_period_coverage(
            db,
            site_id=period.site_id,
            start=period.start_date,
            end=period.end_date,
        )
    outcomes: list[Any] = []
    for index, rider_id in enumerate(rider_ids, start=1):
        outcomes.append(await _settle_one_rider(db, job, period, rider_id, coverage, operator))
        if index % CALC_JOB_BATCH_SIZE == 0:
            await db.flush()
    await db.flush()
    return outcomes


async def _settle_one_rider(
    db: AsyncSession,
    job: RiderSalaryCalcJob,
    period: RiderSalarySettlePeriod,
    rider_id: int,
    coverage: Any,
    operator: Request | None,
) -> Any:
    try:
        async with db.begin_nested():
            result = await calc_service.calculate_rider_period(
                db,
                rider_id=rider_id,
                period=period,
                persist=True,
                operator=operator,
                site_coverage=coverage,
            )
    except CalcPersistSkippedError as exc:
        _merge_warnings(job, [exc.warning])
        job.done_count = int(job.done_count or 0) + 1
        return exc.warning
    except Exception as exc:
        job_no = await _lookup_job_no(db, rider_id)
        _append_failure(job, rider_id, job_no, _failure_reason(exc))
        job.failed_count = int(job.failed_count or 0) + 1
        job.done_count = int(job.done_count or 0) + 1
        return None
    job.success_count = int(job.success_count or 0) + 1
    job.done_count = int(job.done_count or 0) + 1
    _merge_warnings(job, list(result.warnings or []))
    return result


async def _abort_closed_period(db: AsyncSession, job: RiderSalaryCalcJob, period: RiderSalarySettlePeriod) -> bool:
    try:
        await read_period_for_calc(db, period.id)
    except CalcPersistSkippedError as exc:
        await append_period_calc_warning(period.id, exc.warning)
        _merge_warnings(job, [exc.warning])
        job.error_message = exc.warning
        _apply_terminal(job, skipped=True)
        await db.flush()
        return True
    return False


def _apply_terminal(job: RiderSalaryCalcJob, *, skipped: bool, crashed: bool = False) -> None:
    job.status = resolve_calc_job_status(
        success_count=int(job.success_count or 0),
        failed_count=int(job.failed_count or 0),
        skipped=skipped,
        crashed=crashed,
    )
    job.finished_time = timezone.now()


async def _publish_outcomes(period_id: int, outcomes: list[Any]) -> None:
    results = [item for item in outcomes if isinstance(item, CalcResult)]
    skipped = [item for item in outcomes if isinstance(item, str)]
    await record_rider_skips(period_id, results, skipped)


def _has_skip(outcomes: list[Any]) -> bool:
    return any(isinstance(item, str) for item in outcomes)


def _merge_warnings(job: RiderSalaryCalcJob, items: list[str] | None) -> None:
    current = [str(item) for item in (job.warnings or []) if str(item)]
    for item in items or []:
        text = str(item).strip()
        if text and text not in current:
            current.append(text)
    job.warnings = current


def _append_failure(job: RiderSalaryCalcJob, rider_id: int, job_no: str, reason: str) -> None:
    current = [dict(item) for item in (job.failures or []) if isinstance(item, dict)]
    current.append({'rider_id': rider_id, 'job_no': job_no, 'reason': reason})
    job.failures = current


def _target_ids(job: RiderSalaryCalcJob) -> list[int] | None:
    raw = job.target_rider_ids
    if raw is None:
        return None
    return [int(item) for item in raw]


def _operator_id(operator: Request | None) -> int | None:
    if operator is None:
        return None
    user = getattr(operator, 'user', None)
    raw = getattr(user, 'id', None)
    if raw is None:
        return None
    return int(raw)


def _failure_reason(exc: object) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:500]


def _is_active_job_conflict(exc: IntegrityError) -> bool:
    orig = getattr(exc, 'orig', None)
    name = ''
    if orig is not None:
        name = str(getattr(orig, 'constraint_name', None) or '')
        diag = getattr(orig, 'diag', None)
        if not name and diag is not None:
            name = str(getattr(diag, 'constraint_name', None) or '')
    blob = f'{name} {orig or exc}'
    return _ACTIVE_INDEX in blob


async def _lookup_job_no(db: AsyncSession, rider_id: int) -> str:
    value = await db.scalar(select(RiderSalaryRider.job_no).where(RiderSalaryRider.id == rider_id))
    return '' if value is None else str(value)


async def _load_period(db: AsyncSession, period_id: int) -> RiderSalarySettlePeriod:
    period = await db.get(RiderSalarySettlePeriod, period_id)
    if period is None or period.deleted:
        raise errors.NotFoundError(msg='结算周期不存在')
    return period


async def _lock_job(db: AsyncSession, job_id: int) -> RiderSalaryCalcJob | None:
    job = await db.get(RiderSalaryCalcJob, job_id, with_for_update=True)
    if job is None or job.deleted:
        return None
    return job

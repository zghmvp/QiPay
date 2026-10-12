from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.core.conf import settings
from backend.database.db import async_db_session
from backend.plugin.rider_salary.crud.import_batch import import_batch_dao
from backend.plugin.rider_salary.crud.order import order_dao
from backend.plugin.rider_salary.enums import ImportBatchStatus, OrderSource, PeriodStatus
from backend.plugin.rider_salary.model.import_batch import RiderSalaryImportBatch
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.model.site import RiderSalarySite
from backend.plugin.rider_salary.schema.import_batch import (
    GetImportBatchDetail,
    GetImportBatchListItem,
    import_batch_status_label,
)
from backend.plugin.rider_salary.schema.order import ImportErrorItem, ImportResult
from backend.plugin.rider_salary.service.audit_service import snapshot
from backend.plugin.rider_salary.service.order_service import (
    compute_biz_date,
    map_order_status,
    rider_employment_error,
)
from backend.plugin.rider_salary.utils.audit import audit_service, operator_display_name
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.excel import (
    TEMPLATE_HEADERS,
    ExcelReadError,
    parse_cell_datetime,
    read_rows,
    write_workbook,
)
from backend.plugin.rider_salary.utils.lock_check import assert_not_locked, locked_dates_in_range
from backend.plugin.rider_salary.utils.money import q2
from backend.plugin.rider_salary.utils.recalc import mark_stale
from backend.utils.timezone import timezone

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ERROR_RETURN = 100
_BATCH_FIELDS = (
    'id',
    'site_id',
    'file_name',
    'operator_id',
    'total_rows',
    'success_rows',
    'failed_rows',
    'status',
    'date_from',
    'date_to',
    'remark',
)


def build_import_template() -> bytes:
    """生成订单导入模板 xlsx。"""
    example = [
        'CY01',
        'RS001',
        'ORD-DEMO-001',
        '3.50',
        '5.00',
        '2026-09-01 12:00:00',
        '2026-09-01 12:25:00',
        '已完成',
        '25.00',
        '示例数据，导入前请删除',
    ]
    status_rows = [
        ['已完成', 'completed', '完成'],
        ['已取消', 'cancelled', '取消'],
        ['配送异常', 'abnormal', '异常'],
        ['已退款', 'refunded', '退款'],
    ]
    help_rows = [
        ['时间格式：YYYY-MM-DD HH:mm:ss，亦支持 YYYY/M/D H:mm 与 Excel 日期。'],
        ['订单状态请填写：已完成 / 已取消 / 配送异常 / 已退款（可用别名：完成、取消、异常、退款）。'],
        ['业务日期：有送达时间取送达日期，否则取下单日期；跨午夜按送达日归属。'],
        ['带 * 的列为必填；配送距离、商品重量须 ≥ 0；订单金额可空。'],
        ['同一订单号不可重复；库内已存在的订单号不会被覆盖。'],
    ]
    return write_workbook([
        ('订单明细', list(TEMPLATE_HEADERS), [example]),
        ('状态对照', ['中文', '英文码', '兼容别名'], status_rows),
        ('填写说明', ['填写说明'], help_rows),
    ])


def validate_row_format(row: dict[str, Any]) -> str | None:  # ruff:ignore[complex-structure]
    """
    校验单行格式（不查库）

    :param row: read_rows 产出的行字典
    :return:
    """
    if not cell_text(row.get('site_code')):
        return '站点编码不能为空'
    if not cell_text(row.get('job_no')):
        return '工号不能为空'
    if not cell_text(row.get('order_no')):
        return '订单号不能为空'
    distance, distance_err = parse_number(row.get('distance_km'), '配送距离')
    if distance_err:
        return distance_err
    weight, weight_err = parse_number(row.get('weight_jin'), '商品重量')
    if weight_err:
        return weight_err
    if distance is not None and distance < 0:
        return '配送距离不能为负数'
    if weight is not None and weight < 0:
        return '商品重量不能为负数'
    if not cell_text(row.get('order_time')) and not isinstance(row.get('order_time'), (datetime, date, int, float)):
        return '下单时间不能为空'
    try:
        order_time = parse_cell_datetime(row.get('order_time'))
    except ValueError:
        return '下单时间格式不正确'
    deliver_raw = row.get('deliver_time')
    deliver_time = None
    if not _is_blank(deliver_raw):
        try:
            deliver_time = parse_cell_datetime(deliver_raw)
        except ValueError:
            return '送达时间格式不正确'
        if deliver_time < order_time:
            return '送达时间不能早于下单时间'
    amount_raw = row.get('amount')
    if not _is_blank(amount_raw):
        amount, amount_err = parse_number(amount_raw, '订单金额')
        if amount_err:
            return amount_err
        if amount is not None and amount < 0:
            return '订单金额不能为负数'
    if map_order_status(row.get('status')) is None:
        return '订单状态不合法，请填写已完成/已取消/配送异常/已退款'
    return None


def cell_text(value: object) -> str:
    """单元格转字符串。"""
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_number(value: object, label: str) -> tuple[Decimal | None, str | None]:
    """解析数值单元格。"""
    if _is_blank(value):
        return None, f'{label}不能为空'
    try:
        if isinstance(value, Decimal):
            number = value
        elif isinstance(value, bool):
            return None, f'{label}必须为数字'
        elif isinstance(value, (int, float)):
            number = Decimal(str(value))
        else:
            text = str(value).strip().replace(',', '')
            if not text:
                return None, f'{label}不能为空'
            number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None, f'{label}必须为数字'
    return number, None


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    return bool(isinstance(value, str) and not value.strip())


def _max_import_rows() -> int:
    return int(getattr(settings, 'RIDER_SALARY_IMPORT_MAX_ROWS', 20000))


def load_upload_rows(file_bytes: bytes, filename: str) -> list[dict[str, Any]]:
    """上传校验入口：魔数、解压体积、列数和单元格长度。不合法时抛出 HTTP 400。"""
    if len(file_bytes) > MAX_FILE_BYTES:
        raise errors.RequestError(msg=_too_large_msg())
    try:
        return read_rows(file_bytes, filename)
    except ExcelReadError as exc:
        raise errors.RequestError(msg=exc.msg) from None


class ImportService:
    """订单导入服务"""

    @staticmethod
    async def import_orders(  # ruff:ignore[complex-structure]
        *,
        db: AsyncSession,
        request: Request,
        file: UploadFile,
        site_id: int | None,
        skip_errors: bool = False,
        auto_recalc: bool = False,
    ) -> ImportResult:
        """
        导入订单文件

        :param db: 数据库会话
        :param request: 请求对象
        :param file: 上传文件
        :param site_id: 指定站点（可选）
        :param skip_errors: 是否跳过错误行
        :param auto_recalc: 成功后是否在导入事务提交后重算
        :return:
        """
        visible = await get_visible_site_ids(request, db)
        form_site: RiderSalarySite | None = None
        if site_id is not None:
            assert_site_visible(visible, site_id)
            form_site = await db.scalar(
                select(RiderSalarySite).where(RiderSalarySite.id == site_id, RiderSalarySite.deleted == 0)
            )
            if form_site is None:
                raise errors.NotFoundError(msg='站点不存在')
        filename = (file.filename or 'upload.xlsx').rsplit('/', maxsplit=1)[-1]
        if file.size is not None and file.size > MAX_FILE_BYTES:
            raise errors.RequestError(msg=_too_large_msg())
        file_bytes = await file.read()
        rows = load_upload_rows(file_bytes, filename)
        max_rows = _max_import_rows()
        if len(rows) > max_rows:
            raise errors.RequestError(msg=_too_large_msg())

        codes = {cell_text(row.get('site_code')) for row in rows if cell_text(row.get('site_code'))}
        job_nos = {cell_text(row.get('job_no')) for row in rows if cell_text(row.get('job_no'))}
        order_nos = [cell_text(row.get('order_no')) for row in rows if cell_text(row.get('order_no'))]
        sites = {
            item.code: item
            for item in (
                await db.scalars(
                    select(RiderSalarySite).where(RiderSalarySite.code.in_(codes), RiderSalarySite.deleted == 0)
                )
            ).all()
        }
        riders = {
            item.job_no: item
            for item in (
                await db.scalars(
                    select(RiderSalaryRider).where(RiderSalaryRider.job_no.in_(job_nos), RiderSalaryRider.deleted == 0)
                )
            ).all()
        }
        existing_nos = await order_dao.get_existing_order_nos(db, order_nos)

        file_seen: dict[str, int] = {}
        lock_cache: dict[tuple[int, int, date], bool] = {}
        await _prefetch_import_locks(
            db=db,
            rows=rows,
            visible=visible,
            form_site=form_site,
            sites=sites,
            riders=riders,
            existing_nos=existing_nos,
            lock_cache=lock_cache,
        )
        error_items: list[dict[str, Any]] = []
        prepared: list[dict[str, Any]] = []

        for row in rows:
            row_no = int(row.get('_row') or 0)
            order_no = cell_text(row.get('order_no')) or None
            reason = await _validate_import_row(
                db=db,
                row=row,
                visible=visible,
                form_site=form_site,
                sites=sites,
                riders=riders,
                existing_nos=existing_nos,
                file_seen=file_seen,
                lock_cache=lock_cache,
            )
            if reason:
                error_items.append({'row': row_no, 'order_no': order_no, 'reason': reason})
                continue
            prepared.append(row)

        total_rows = len(rows)
        failed_rows = len(error_items)
        if not skip_errors and failed_rows:
            prepared = []
            success_rows = 0
            batch_status = ImportBatchStatus.failed.value
        elif not prepared and failed_rows:
            success_rows = 0
            batch_status = ImportBatchStatus.failed.value
        elif failed_rows:
            success_rows = len(prepared)
            batch_status = ImportBatchStatus.partial_failed.value
        else:
            success_rows = len(prepared)
            batch_status = ImportBatchStatus.success.value

        inserted = _build_orders(prepared)
        rider_ids = {item.rider_id for item in inserted}
        biz_dates = [item.biz_date for item in inserted]
        date_from = min(biz_dates) if biz_dates else None
        date_to = max(biz_dates) if biz_dates else None
        batch_site_id = _resolve_batch_site_id(form_site, prepared, sites)
        if batch_site_id is None:
            raise errors.RequestError(
                msg='无法确定导入站点，请指定 site_id 或检查站点编码',
                data=_result_payload(
                    batch_id=None,
                    total_rows=total_rows,
                    success_rows=0,
                    failed_rows=failed_rows or total_rows,
                    status=ImportBatchStatus.failed.value,
                    errors=error_items,
                ),
            )
        assert_site_visible(visible, batch_site_id)
        site_name = form_site.name if form_site is not None else _site_name(batch_site_id, sites)

        batch = RiderSalaryImportBatch(
            site_id=batch_site_id,
            file_name=filename,
            operator_id=int(getattr(request.user, 'id', 0) or 0),
            total_rows=total_rows,
            success_rows=success_rows,
            failed_rows=failed_rows,
            status=batch_status,
            date_from=date_from,
            date_to=date_to,
            error_report=error_items or [],
        )
        db.add(batch)
        await db.flush()
        if inserted:
            for order in inserted:
                order.import_batch_id = batch.id
            db.add_all(inserted)
            await db.flush()
            if date_from is not None and date_to is not None:
                await mark_stale(db, rider_ids=rider_ids, date_from=date_from, date_to=date_to)
        await audit_service.record(
            db,
            request,
            module='订单明细',
            action='导入订单',
            target_type='import_batch',
            target_id=batch.id,
            target_label=f'站点{site_name}',
            before={'exists': False, 'site_id': batch_site_id, 'file_name': filename},
            after=snapshot(batch, _BATCH_FIELDS),
            description=(
                f'{operator_display_name(request)} 于 {_now_str()} 对 站点{site_name} 执行了导入订单，'
                f'文件{filename}，成功{success_rows}行，失败{failed_rows}行'
            ),
        )
        if inserted:
            date_from_text = date_from.isoformat() if date_from is not None else None
            date_to_text = date_to.isoformat() if date_to is not None else None
            await audit_service.record(
                db,
                request,
                module='订单明细',
                action='导入订单',
                target_type='order',
                target_id=None,
                target_label=f'站点{site_name}',
                site_id=batch_site_id,
                before={'exists': False, 'count': 0},
                after={
                    'count': success_rows,
                    'date_from': date_from_text,
                    'date_to': date_to_text,
                    'rider_count': len(rider_ids),
                },
                description=(
                    f'{operator_display_name(request)} 于 {_now_str()} 对 站点{site_name} 写入订单，'
                    f'成功{success_rows}条，业务日期{date_from_text}至{date_to_text}'
                ),
            )
        if auto_recalc and inserted and date_from is not None and date_to is not None:
            from backend.plugin.rider_salary.service.calc_job_service import schedule_import_recalc

            await schedule_import_recalc(
                db,
                site_id=batch_site_id,
                rider_ids=list(rider_ids),
                date_from=date_from,
                date_to=date_to,
                operator_id=int(getattr(request.user, 'id', 0) or 0),
            )
        return ImportResult(
            batch_id=batch.id,
            total_rows=total_rows,
            success_rows=success_rows,
            failed_rows=failed_rows,
            status=batch_status,
            errors=[ImportErrorItem(**item) for item in error_items[:MAX_ERROR_RETURN]],
        )

    @staticmethod
    async def get_batch(*, db: AsyncSession, request: Request, pk: int) -> GetImportBatchDetail:
        """
        获取导入批次详情

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 批次 ID
        :return:
        """
        batch = await import_batch_dao.get(db, pk)
        if batch is None:
            raise errors.NotFoundError(msg='导入批次不存在')
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, batch.site_id)
        return await _to_batch_detail(db, batch)

    @staticmethod
    async def get_batch_list(
        *,
        db: AsyncSession,
        request: Request,
        site_id: int | None,
        status: str | None,
    ) -> dict[str, Any]:
        """
        分页获取导入批次

        :param db: 数据库会话
        :param request: 请求对象
        :param site_id: 站点 ID
        :param status: 批次状态
        :return:
        """
        visible = await get_visible_site_ids(request, db)
        if site_id is not None:
            assert_site_visible(visible, site_id)
        stmt = await import_batch_dao.get_select(site_ids=visible, site_id=site_id, status=status)
        page_data = await paging_data(db, stmt)
        page_data['items'] = await _to_batch_list_items(db, list(page_data['items']))
        return page_data

    @staticmethod
    async def get_error_report(*, db: AsyncSession, request: Request, pk: int) -> bytes:
        """
        生成错误报告 xlsx

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 批次 ID
        :return:
        """
        batch = await import_batch_dao.get(db, pk)
        if batch is None:
            raise errors.NotFoundError(msg='导入批次不存在')
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, batch.site_id)
        report = batch.error_report or []
        rows: list[list] = []
        for item in report:
            if isinstance(item, dict):
                rows.append([item.get('row'), item.get('order_no'), item.get('reason')])
            else:
                rows.append([None, None, str(item)])
        return write_workbook([('错误报告', ['行号', '订单号', '原因'], rows)])


def _import_recalc_period_stmt(
    *,
    site_id: int,
    rider_ids: list[int],
    date_from: date,
    date_to: date,
) -> Any:
    """导入区间内、这些骑手会碰到的周期（含已锁账、已发薪）。"""
    return select(RiderSalarySettlePeriod).where(
        RiderSalarySettlePeriod.site_id == site_id,
        RiderSalarySettlePeriod.status.in_([
            PeriodStatus.open,
            PeriodStatus.reopened,
            PeriodStatus.locked,
            PeriodStatus.paid,
        ]),
        RiderSalarySettlePeriod.start_date <= date_to,
        RiderSalarySettlePeriod.end_date >= date_from,
        RiderSalarySettlePeriod.deleted == 0,
        RiderSalarySettlePeriod.rider_id.in_([*rider_ids, 0]),
    )


async def _recalc_one_imported_period(
    db: AsyncSession,
    *,
    period: RiderSalarySettlePeriod,
    rider_ids: list[int],
) -> bool:
    """重算一个周期。失败只回滚这个周期的保存点，并把原因写成可见告警。

    :return: 没有抛错时为真
    """
    from backend.common.log import log
    from backend.plugin.rider_salary.service.calc_service import append_period_calc_warning, calculate_period

    try:
        async with db.begin_nested():
            await calculate_period(db, period_id=period.id, rider_ids=rider_ids, operator=None)
    except Exception as exc:
        log.exception('导入后自动重算失败 period_id=%s', period.id)
        await append_period_calc_warning(period.id, f'导入后自动重算失败：{exc}')
        return False
    return True


async def recalc_imported_periods_on(
    db: AsyncSession,
    *,
    site_id: int,
    rider_ids: list[int],
    date_from: date,
    date_to: date,
    operator_id: int,
) -> None:
    """在调用方会话里重算导入涉及的周期。

    :param db: 数据库会话
    :param site_id: 站点 ID
    :param rider_ids: 骑手 ID
    :param date_from: 业务日起
    :param date_to: 业务日止
    :param operator_id: 操作人 ID
    """
    _ = operator_id
    periods = list(
        (
            await db.scalars(
                _import_recalc_period_stmt(
                    site_id=site_id,
                    rider_ids=rider_ids,
                    date_from=date_from,
                    date_to=date_to,
                )
            )
        ).all()
    )
    for period in periods:
        await _recalc_period_under_job(db, period=period, rider_ids=rider_ids, operator_id=operator_id)


async def recalc_imported_periods(
    *,
    site_id: int,
    rider_ids: list[int],
    date_from: date,
    date_to: date,
    operator_id: int,
) -> None:
    """导入后后台重算涉及的周期。已锁账的跳过且留下告警；失败不影响已入库订单。

    每个周期先提交一条计算中作业，锁账能看见它，再重算，最后提交终态。
    """
    from backend.common.log import log

    try:
        async with async_db_session.begin() as db:
            period_ids = [
                int(row.id)
                for row in (
                    await db.scalars(
                        _import_recalc_period_stmt(
                            site_id=site_id,
                            rider_ids=rider_ids,
                            date_from=date_from,
                            date_to=date_to,
                        )
                    )
                ).all()
            ]
        for period_id in period_ids:
            await _recalc_committed_period_job(period_id, rider_ids, operator_id)
    except Exception as exc:
        log.exception('导入后自动重算失败 site_id=%s rider_ids=%s', site_id, rider_ids)
        await _warn_import_recalc_failure(
            site_id=site_id,
            rider_ids=rider_ids,
            date_from=date_from,
            date_to=date_to,
            exc=exc,
        )


async def _recalc_period_under_job(
    db: AsyncSession,
    *,
    period: RiderSalarySettlePeriod,
    rider_ids: list[int],
    operator_id: int,
) -> None:
    """在当前事务里挂上计算中作业，算完后写成终态。"""
    from sqlalchemy.exc import IntegrityError

    from backend.plugin.rider_salary.enums import CalcJobStatus
    from backend.plugin.rider_salary.model.calc_job import RiderSalaryCalcJob
    from backend.plugin.rider_salary.service.calc_job_service import period_has_active_job
    from backend.plugin.rider_salary.service.calc_service import PERIOD_CALCULATING_LOCK_MSG, append_period_calc_warning
    from backend.utils.timezone import timezone

    if await period_has_active_job(db, period.id):
        await append_period_calc_warning(period.id, PERIOD_CALCULATING_LOCK_MSG)
        return
    job = RiderSalaryCalcJob(
        period_id=period.id,
        site_id=period.site_id,
        status=CalcJobStatus.running.value,
        operator_id=operator_id or None,
    )
    try:
        async with db.begin_nested():
            db.add(job)
            await db.flush()
    except IntegrityError:
        await append_period_calc_warning(period.id, PERIOD_CALCULATING_LOCK_MSG)
        return
    ok = await _recalc_one_imported_period(db, period=period, rider_ids=rider_ids)
    job.status = CalcJobStatus.succeeded.value if ok else CalcJobStatus.failed.value
    job.finished_time = timezone.now()
    if not ok:
        job.error_message = '导入后自动重算失败'
    await db.flush()


async def _recalc_committed_period_job(period_id: int, rider_ids: list[int], operator_id: int) -> None:
    """先提交计算中作业，再重算，最后提交终态。锁账在重算期间会看到这条作业。"""
    from backend.common.log import log
    from backend.plugin.rider_salary.service.calc_service import append_period_calc_warning

    job_id = await _open_running_import_job(period_id, operator_id)
    if job_id is None:
        return
    try:
        ok = await _recalc_loaded_period(period_id, rider_ids)
    except Exception as exc:
        log.exception('导入后自动重算失败 period_id=%s', period_id)
        await append_period_calc_warning(period_id, f'导入后自动重算失败：{exc}')
        await _close_import_job(job_id, ok=False, message=str(exc)[:500])
        return
    message = None if ok else '导入后自动重算失败'
    await _close_import_job(job_id, ok=ok, message=message)


async def _open_running_import_job(period_id: int, operator_id: int) -> int | None:
    """提交一条计算中作业。已有活动作业时不新建。"""
    from backend.plugin.rider_salary.enums import CalcJobStatus
    from backend.plugin.rider_salary.model.calc_job import RiderSalaryCalcJob
    from backend.plugin.rider_salary.service.calc_job_service import period_has_active_job
    from backend.plugin.rider_salary.service.calc_service import PERIOD_CALCULATING_LOCK_MSG, append_period_calc_warning

    async with async_db_session.begin() as db:
        period = await db.get(RiderSalarySettlePeriod, period_id)
        if period is None or period.deleted:
            return None
        if await period_has_active_job(db, period.id):
            await append_period_calc_warning(period.id, PERIOD_CALCULATING_LOCK_MSG)
            return None
        job = RiderSalaryCalcJob(
            period_id=period.id,
            site_id=period.site_id,
            status=CalcJobStatus.running.value,
            operator_id=operator_id or None,
        )
        db.add(job)
        await db.flush()
        return int(job.id)


async def _recalc_loaded_period(period_id: int, rider_ids: list[int]) -> bool:
    async with async_db_session.begin() as db:
        period = await db.get(RiderSalarySettlePeriod, period_id)
        if period is None or period.deleted:
            return False
        return await _recalc_one_imported_period(db, period=period, rider_ids=rider_ids)


async def _close_import_job(job_id: int, *, ok: bool, message: str | None) -> None:
    from backend.common.log import log
    from backend.plugin.rider_salary.enums import CalcJobStatus
    from backend.plugin.rider_salary.model.calc_job import RiderSalaryCalcJob
    from backend.utils.timezone import timezone

    try:
        async with async_db_session.begin() as db:
            stored = await db.get(RiderSalaryCalcJob, job_id)
            if stored is None or stored.status != CalcJobStatus.running.value:
                return
            stored.status = CalcJobStatus.succeeded.value if ok else CalcJobStatus.failed.value
            stored.finished_time = timezone.now()
            if message:
                stored.error_message = message
    except Exception:
        log.exception('回写导入重算作业失败 job_id=%s', job_id)


async def _warn_import_recalc_failure(
    *,
    site_id: int,
    rider_ids: list[int],
    date_from: date,
    date_to: date,
    exc: Exception,
) -> None:
    """整段重算没能进事务时，另开一次会话把失败写到相关周期上。"""
    from backend.common.log import log
    from backend.plugin.rider_salary.service.calc_service import append_period_calc_warning

    try:
        async with async_db_session.begin() as db:
            periods = list(
                (
                    await db.scalars(
                        _import_recalc_period_stmt(
                            site_id=site_id,
                            rider_ids=rider_ids,
                            date_from=date_from,
                            date_to=date_to,
                        )
                    )
                ).all()
            )
            for period in periods:
                await append_period_calc_warning(period.id, f'导入后自动重算失败：{exc}')
    except Exception:
        log.exception('导入后自动重算失败且告警未能写入 site_id=%s', site_id)


async def _validate_import_row(  # ruff:ignore[complex-structure]
    *,
    db: AsyncSession,
    row: dict[str, Any],
    visible: set[int] | None,
    form_site: RiderSalarySite | None,
    sites: dict[str, RiderSalarySite],
    riders: dict[str, RiderSalaryRider],
    existing_nos: set[str],
    file_seen: dict[str, int],
    lock_cache: dict[tuple[int, int, date], bool],
) -> str | None:
    format_error = validate_row_format(row)
    if format_error:
        return format_error
    site_code = cell_text(row.get('site_code'))
    job_no = cell_text(row.get('job_no'))
    order_no = cell_text(row.get('order_no'))
    site = sites.get(site_code)
    if site is None:
        return '站点编码不存在'
    if visible is not None and site.id not in visible:
        return '无权访问该站点数据'
    if form_site is not None and site.id != form_site.id:
        return '站点编码与指定站点不一致'
    rider = riders.get(job_no)
    if rider is None:
        return '工号不存在'
    if rider.site_id != site.id:
        return f'骑手 {job_no} 不属于站点 {site_code}'
    first_row = file_seen.get(order_no)
    if first_row is not None:
        return f'订单号 {order_no} 在本文件中重复'
    file_seen[order_no] = int(row.get('_row') or 0)
    if order_no in existing_nos:
        return f'订单号 {order_no} 已存在'
    order_time = parse_cell_datetime(row.get('order_time'))
    deliver_time = None if _is_blank(row.get('deliver_time')) else parse_cell_datetime(row.get('deliver_time'))
    biz_date = compute_biz_date(order_time, deliver_time)
    emp_error = rider_employment_error(rider, biz_date)
    if emp_error:
        return emp_error
    locked = await _is_locked(db, site.id, rider.id, biz_date, lock_cache)
    if locked:
        return '订单所属周期已锁账，请走反冲补发'
    row['_site'] = site
    row['_rider'] = rider
    row['_order_time'] = order_time
    row['_deliver_time'] = deliver_time
    row['_biz_date'] = biz_date
    row['_status'] = map_order_status(row.get('status'))
    distance, _ = parse_number(row.get('distance_km'), '配送距离')
    weight, _ = parse_number(row.get('weight_jin'), '商品重量')
    row['_distance'] = distance
    row['_weight'] = weight
    if _is_blank(row.get('amount')):
        row['_amount'] = None
    else:
        amount, _ = parse_number(row.get('amount'), '订单金额')
        row['_amount'] = amount
    row['_order_no'] = order_no
    row['_remark'] = cell_text(row.get('remark')) or None
    return None


def _build_orders(prepared: list[dict[str, Any]]) -> list[RiderSalaryOrder]:
    orders: list[RiderSalaryOrder] = []
    for row in prepared:
        site: RiderSalarySite = row['_site']
        rider: RiderSalaryRider = row['_rider']
        orders.append(
            RiderSalaryOrder(
                order_no=row['_order_no'],
                site_id=site.id,
                rider_id=rider.id,
                biz_date=row['_biz_date'],
                distance_km=q2(row['_distance']),
                weight_jin=q2(row['_weight']),
                order_time=row['_order_time'],
                deliver_time=row['_deliver_time'],
                status=row['_status'],
                amount=q2(row['_amount']) if row['_amount'] is not None else None,
                source=OrderSource.import_.value,
                remark=row['_remark'],
            )
        )
    return orders


def _resolve_batch_site_id(
    form_site: RiderSalarySite | None,
    prepared: list[dict[str, Any]],
    sites: dict[str, RiderSalarySite],
) -> int | None:
    if form_site is not None:
        return form_site.id
    ids = {row['_site'].id for row in prepared if '_site' in row}
    if len(ids) == 1:
        return next(iter(ids))
    if len(sites) == 1:
        return next(iter(sites.values())).id
    return None


def _site_name(site_id: int, sites: dict[str, RiderSalarySite]) -> str:
    for site in sites.values():
        if site.id == site_id:
            return site.name
    return str(site_id)


def _too_large_msg() -> str:
    return f'文件过大，单次最多 {_max_import_rows()} 行或 10MB，请拆分后上传'


def _result_payload(
    *,
    batch_id: int | None,
    total_rows: int,
    success_rows: int,
    failed_rows: int,
    status: str,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        'batch_id': batch_id,
        'total_rows': total_rows,
        'success_rows': success_rows,
        'failed_rows': failed_rows,
        'status': status,
        'errors': errors[:MAX_ERROR_RETURN],
    }


def _import_lock_target(
    *,
    row: dict[str, Any],
    visible: set[int] | None,
    form_site: RiderSalarySite | None,
    sites: dict[str, RiderSalarySite],
    riders: dict[str, RiderSalaryRider],
    existing_nos: set[str],
) -> tuple[int, int, date] | None:
    """与逐行校验到达锁账之前的判断对齐。到不了锁账的行不预取。"""
    if validate_row_format(row):
        return None
    site = sites.get(cell_text(row.get('site_code')))
    if site is None:
        return None
    if visible is not None and site.id not in visible:
        return None
    if form_site is not None and site.id != form_site.id:
        return None
    rider = riders.get(cell_text(row.get('job_no')))
    if rider is None or rider.site_id != site.id:
        return None
    if cell_text(row.get('order_no')) in existing_nos:
        return None
    order_time = parse_cell_datetime(row.get('order_time'))
    deliver_raw = row.get('deliver_time')
    deliver_time = None if _is_blank(deliver_raw) else parse_cell_datetime(deliver_raw)
    biz_date = compute_biz_date(order_time, deliver_time)
    if rider_employment_error(rider, biz_date):
        return None
    return site.id, rider.id, biz_date


async def _prefetch_import_locks(
    *,
    db: AsyncSession,
    rows: list[dict[str, Any]],
    visible: set[int] | None,
    form_site: RiderSalarySite | None,
    sites: dict[str, RiderSalarySite],
    riders: dict[str, RiderSalaryRider],
    existing_nos: set[str],
    lock_cache: dict[tuple[int, int, date], bool],
) -> None:
    """按骑手一次取出区间内锁账日期，写入逐行缓存。查询次数等于涉及的站点+骑手组合数。"""
    spans: dict[tuple[int, int], list[date]] = {}
    for row in rows:
        target = _import_lock_target(
            row=row,
            visible=visible,
            form_site=form_site,
            sites=sites,
            riders=riders,
            existing_nos=existing_nos,
        )
        if target is None:
            continue
        site_id, rider_id, biz_date = target
        spans.setdefault((site_id, rider_id), []).append(biz_date)
    for (site_id, rider_id), days in spans.items():
        date_from = min(days)
        date_to = max(days)
        locked = await locked_dates_in_range(
            db,
            site_id=site_id,
            rider_id=rider_id,
            date_from=date_from,
            date_to=date_to,
        )
        current = date_from
        while current <= date_to:
            lock_cache[site_id, rider_id, current] = current in locked
            current += timedelta(days=1)


async def _is_locked(
    db: AsyncSession,
    site_id: int,
    rider_id: int,
    biz_date: date,
    cache: dict[tuple[int, int, date], bool],
) -> bool:
    key = (site_id, rider_id, biz_date)
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        await assert_not_locked(db, site_id=site_id, rider_id=rider_id, biz_date=biz_date)
    except errors.ForbiddenError:
        cache[key] = True
        return True
    cache[key] = False
    return False


def _now_str() -> str:
    return timezone.to_str(timezone.now())


async def _to_batch_detail(db: AsyncSession, batch: RiderSalaryImportBatch) -> GetImportBatchDetail:
    site = await db.scalar(select(RiderSalarySite).where(RiderSalarySite.id == batch.site_id))
    detail = GetImportBatchDetail.model_validate(batch)
    return detail.model_copy(
        update={
            'site_name': site.name if site else '',
            'status_label': import_batch_status_label(batch.status),
        }
    )


async def _to_batch_list_items(db: AsyncSession, batches: Sequence[Any]) -> list[GetImportBatchListItem]:
    models = [item for item in batches if isinstance(item, RiderSalaryImportBatch)]
    if len(models) != len(batches) and batches:
        ids: list[int] = []
        for item in batches:
            if isinstance(item, RiderSalaryImportBatch):
                ids.append(item.id)
            elif isinstance(item, dict):
                ids.append(int(item['id']))
            else:
                ids.append(int(item.id))
        result = await db.scalars(select(RiderSalaryImportBatch).where(RiderSalaryImportBatch.id.in_(ids)))
        by_id = {item.id: item for item in result.all()}
        models = [by_id[pk] for pk in ids if pk in by_id]
    if not models:
        return []
    site_ids = {item.site_id for item in models}
    sites = {
        item.id: item
        for item in (await db.scalars(select(RiderSalarySite).where(RiderSalarySite.id.in_(site_ids)))).all()
    }
    items: list[GetImportBatchListItem] = []
    for batch in models:
        site = sites.get(batch.site_id)
        detail = GetImportBatchListItem.model_validate(batch)
        items.append(
            detail.model_copy(
                update={
                    'site_name': site.name if site else '',
                    'status_label': import_batch_status_label(batch.status),
                }
            )
        )
    return items


import_service: ImportService = ImportService()

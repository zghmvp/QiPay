from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.plugin.rider_salary.crud.order import order_dao
from backend.plugin.rider_salary.enums import OrderSource, OrderStatus
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.site import RiderSalarySite
from backend.plugin.rider_salary.schema.order import (
    CreateOrderParam,
    GetOrderDetail,
    UpdateOrderParam,
    order_source_label,
    order_status_label,
)
from backend.plugin.rider_salary.utils.audit import audit_service
from backend.plugin.rider_salary.utils.deps import assert_site_visible, get_visible_site_ids
from backend.plugin.rider_salary.utils.excel import write_workbook
from backend.plugin.rider_salary.utils.lock_check import assert_not_locked
from backend.plugin.rider_salary.utils.money import q2
from backend.plugin.rider_salary.utils.recalc import mark_stale
from backend.utils.timezone import timezone

ORDER_EXPORT_HEADERS = [
    '站点编码',
    '站点名称',
    '骑手工号',
    '骑手姓名',
    '订单号',
    '配送距离(公里)',
    '商品重量(斤)',
    '下单时间',
    '送达时间',
    '订单状态',
    '订单金额',
    '备注',
    '来源',
    '业务日期',
    '是否锁账',
]


def compute_biz_date(order_time: datetime, deliver_time: datetime | None) -> date:
    """业务日期：有送达取送达日，否则取下单日。"""
    if deliver_time is not None:
        return timezone.from_datetime(deliver_time).date() if deliver_time.tzinfo else deliver_time.date()
    return timezone.from_datetime(order_time).date() if order_time.tzinfo else order_time.date()


def map_order_status(raw: object) -> str | None:
    """将中文 / 英文 / 别名映射为订单状态枚举值。"""
    text = '' if raw is None else str(raw).strip()
    if not text:
        return None
    aliases = {
        '已完成': OrderStatus.completed.value,
        '完成': OrderStatus.completed.value,
        'completed': OrderStatus.completed.value,
        '已取消': OrderStatus.cancelled.value,
        '取消': OrderStatus.cancelled.value,
        'cancelled': OrderStatus.cancelled.value,
        'canceled': OrderStatus.cancelled.value,
        '配送异常': OrderStatus.abnormal.value,
        '异常': OrderStatus.abnormal.value,
        'abnormal': OrderStatus.abnormal.value,
        '已退款': OrderStatus.refunded.value,
        '退款': OrderStatus.refunded.value,
        'refunded': OrderStatus.refunded.value,
    }
    return aliases.get(text) or aliases.get(text.lower())


def rider_employment_error(rider: RiderSalaryRider, biz_date: date) -> str | None:
    """校验业务日期是否落在入职～离职区间内。"""
    if biz_date < rider.hire_date:
        return f'骑手入职日期为 {rider.hire_date}，该业务日期早于入职'
    if rider.leave_date is not None and biz_date > rider.leave_date:
        return f'骑手已于 {rider.leave_date} 离职'
    return None


def order_snapshot(order: RiderSalaryOrder) -> dict[str, Any]:
    """审计 before/after 快照。"""
    return {
        'order_no': order.order_no,
        'site_id': order.site_id,
        'rider_id': order.rider_id,
        'biz_date': str(order.biz_date),
        'distance_km': str(order.distance_km),
        'weight_jin': str(order.weight_jin),
        'order_time': timezone.to_str(order.order_time) if order.order_time else None,
        'deliver_time': timezone.to_str(order.deliver_time) if order.deliver_time else None,
        'status': order.status,
        'amount': str(order.amount) if order.amount is not None else None,
        'remark': order.remark,
        'source': order.source,
        'is_locked': order.is_locked,
    }


class OrderService:
    """订单明细服务"""

    @staticmethod
    async def get(*, db: AsyncSession, request: Request, pk: int) -> GetOrderDetail:
        """
        获取订单详情

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 订单 ID
        :return:
        """
        order = await order_dao.get(db, pk)
        if order is None:
            raise errors.NotFoundError(msg='订单不存在')
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, order.site_id)
        details = await _to_details(db, [order])
        return details[0]

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        request: Request,
        site_id: int | None,
        rider_id: int | None,
        date_from: date | None,
        date_to: date | None,
        status: str | None,
        order_no: str | None,
        import_batch_id: int | None,
        is_locked: bool | None,
        attention: bool | None = None,
    ) -> dict[str, Any]:
        """
        分页获取订单

        :param db: 数据库会话
        :param request: 请求对象
        :param site_id: 站点 ID
        :param rider_id: 骑手 ID
        :param date_from: 业务日期起
        :param date_to: 业务日期止
        :param status: 订单状态
        :param order_no: 订单号
        :param import_batch_id: 导入批次
        :param is_locked: 是否锁账
        :param attention: 需关注（异常∪退款∪超时，与工作台同源）
        :return:
        """
        visible = await get_visible_site_ids(request, db)
        if site_id is not None:
            assert_site_visible(visible, site_id)
        mapped_status = None
        if status and not attention:
            mapped_status = map_order_status(status) or status
        stmt = await order_dao.get_select(
            site_ids=visible,
            site_id=site_id,
            rider_id=rider_id,
            date_from=date_from,
            date_to=date_to,
            status=mapped_status,
            order_no=order_no,
            import_batch_id=import_batch_id,
            is_locked=is_locked,
            attention=attention,
        )
        page_data = await paging_data(db, stmt)
        page_data['items'] = await _to_details(db, list(page_data['items']))
        return page_data

    @staticmethod
    async def export(
        *,
        db: AsyncSession,
        request: Request,
        site_id: int,
        date_from: date | None,
        date_to: date | None,
        rider_id: int | None,
    ) -> tuple[bytes, str]:
        """
        导出订单明细 xlsx

        :param db: 数据库会话
        :param request: 请求对象
        :param site_id: 站点 ID
        :param date_from: 业务日期起
        :param date_to: 业务日期止
        :param rider_id: 骑手 ID
        :return: 文件字节, 文件名
        """
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, site_id)
        site = await _get_site(db, site_id)
        stmt = await order_dao.get_select(
            site_ids=visible,
            site_id=site_id,
            rider_id=rider_id,
            date_from=date_from,
            date_to=date_to,
            status=None,
            order_no=None,
            import_batch_id=None,
            is_locked=None,
        )
        orders = list((await db.scalars(stmt)).all())
        details = await _to_details(db, orders)
        rows: list[list] = [
            [
                site.code,
                item.site_name or site.name,
                item.rider_job_no,
                item.rider_name,
                item.order_no,
                str(item.distance_km),
                str(item.weight_jin),
                timezone.to_str(item.order_time) if item.order_time else '',
                timezone.to_str(item.deliver_time) if item.deliver_time else '',
                item.status_label or item.status,
                str(item.amount) if item.amount is not None else '',
                item.remark or '',
                item.source_label or item.source,
                item.biz_date.isoformat() if item.biz_date else '',
                '是' if item.is_locked else '否',
            ]
            for item in details
        ]
        content = write_workbook([('订单明细', ORDER_EXPORT_HEADERS, rows)])
        from_text = date_from.isoformat() if date_from else '全部'
        to_text = date_to.isoformat() if date_to else '全部'
        filename = f'订单明细_{site.name}_{from_text}_{to_text}.xlsx'
        await audit_service.record(
            db,
            request,
            module='订单明细',
            action='导出订单',
            target_type='order',
            target_id=site_id,
            target_label=f'站点{site.name}',
        )
        return content, filename

    @staticmethod
    async def create(*, db: AsyncSession, request: Request, obj: CreateOrderParam) -> GetOrderDetail:
        """
        单条补录

        :param db: 数据库会话
        :param request: 请求对象
        :param obj: 补录参数
        :return:
        """
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, obj.site_id)
        site = await _get_site(db, obj.site_id)
        rider = await _get_rider(db, obj.rider_id)
        if rider.site_id != site.id:
            raise errors.RequestError(msg='骑手不属于当前站点')
        mapped = map_order_status(obj.status)
        if mapped is None:
            raise errors.RequestError(msg='订单状态不合法，请填写已完成/已取消/配送异常/已退款')
        if obj.distance_km < 0:
            raise errors.RequestError(msg='配送距离不能为负数')
        if obj.weight_jin < 0:
            raise errors.RequestError(msg='商品重量不能为负数')
        if obj.amount is not None and obj.amount < 0:
            raise errors.RequestError(msg='订单金额不能为负数')
        if obj.deliver_time is not None and obj.deliver_time < obj.order_time:
            raise errors.RequestError(msg='送达时间不能早于下单时间')
        biz_date = compute_biz_date(obj.order_time, obj.deliver_time)
        emp_error = rider_employment_error(rider, biz_date)
        if emp_error:
            raise errors.RequestError(msg=emp_error)
        await assert_not_locked(db, site_id=site.id, rider_id=rider.id, biz_date=biz_date)
        existed = await order_dao.get_by_order_no(db, obj.order_no.strip())
        if existed:
            raise errors.RequestError(msg='订单号已存在')
        order = RiderSalaryOrder(
            order_no=obj.order_no.strip(),
            site_id=site.id,
            rider_id=rider.id,
            biz_date=biz_date,
            distance_km=q2(obj.distance_km),
            weight_jin=q2(obj.weight_jin),
            order_time=obj.order_time,
            deliver_time=obj.deliver_time,
            status=mapped,
            amount=q2(obj.amount) if obj.amount is not None else None,
            source=OrderSource.manual.value,
            remark=obj.remark,
        )
        db.add(order)
        await db.flush()
        await mark_stale(db, rider_ids=[rider.id], date_from=biz_date, date_to=biz_date)
        await audit_service.record(
            db,
            request,
            module='订单明细',
            action='订单补录',
            target_type='order',
            target_id=order.id,
            target_label=f'订单{order.order_no}',
            after=order_snapshot(order),
        )
        details = await _to_details(db, [order])
        return details[0]

    @staticmethod
    async def update(  # ruff:ignore[complex-structure]
        *, db: AsyncSession, request: Request, pk: int, obj: UpdateOrderParam
    ) -> GetOrderDetail:
        """
        订单纠错

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 订单 ID
        :param obj: 纠错参数
        :return:
        """
        order = await order_dao.get(db, pk)
        if order is None:
            raise errors.NotFoundError(msg='订单不存在')
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, order.site_id)
        if order.is_locked:
            raise errors.ForbiddenError(msg='该日期所属结算周期已锁账，禁止修改，请走反冲补发流程')
        old_rider_id = order.rider_id
        old_biz_date = order.biz_date
        before = order_snapshot(order)
        payload = obj.model_dump(exclude_unset=True, exclude={'reason'})
        if 'order_no' in payload and payload['order_no'] is not None:
            new_no = str(payload['order_no']).strip()
            existed = await order_dao.get_by_order_no(db, new_no)
            if existed is not None and existed.id != order.id:
                raise errors.RequestError(msg='订单号已存在')
            order.order_no = new_no
        if 'site_id' in payload and payload['site_id'] is not None:
            assert_site_visible(visible, int(payload['site_id']))
            order.site_id = int(payload['site_id'])
        if 'rider_id' in payload and payload['rider_id'] is not None:
            order.rider_id = int(payload['rider_id'])
        if 'distance_km' in payload and payload['distance_km'] is not None:
            if payload['distance_km'] < 0:
                raise errors.RequestError(msg='配送距离不能为负数')
            order.distance_km = q2(payload['distance_km'])
        if 'weight_jin' in payload and payload['weight_jin'] is not None:
            if payload['weight_jin'] < 0:
                raise errors.RequestError(msg='商品重量不能为负数')
            order.weight_jin = q2(payload['weight_jin'])
        if 'order_time' in payload and payload['order_time'] is not None:
            order.order_time = payload['order_time']
        if 'deliver_time' in payload:
            order.deliver_time = payload['deliver_time']
        if 'status' in payload and payload['status'] is not None:
            mapped = map_order_status(payload['status'])
            if mapped is None:
                raise errors.RequestError(msg='订单状态不合法，请填写已完成/已取消/配送异常/已退款')
            order.status = mapped
        if 'amount' in payload:
            amount = payload['amount']
            if amount is not None and amount < 0:
                raise errors.RequestError(msg='订单金额不能为负数')
            order.amount = q2(amount) if amount is not None else None
        if 'remark' in payload:
            order.remark = payload['remark']
        if order.deliver_time is not None and order.deliver_time < order.order_time:
            raise errors.RequestError(msg='送达时间不能早于下单时间')
        site = await _get_site(db, order.site_id)
        rider = await _get_rider(db, order.rider_id)
        if rider.site_id != site.id:
            raise errors.RequestError(msg='骑手不属于当前站点')
        order.biz_date = compute_biz_date(order.order_time, order.deliver_time)
        emp_error = rider_employment_error(rider, order.biz_date)
        if emp_error:
            raise errors.RequestError(msg=emp_error)
        await assert_not_locked(db, site_id=order.site_id, rider_id=order.rider_id, biz_date=order.biz_date)
        if old_rider_id != order.rider_id or old_biz_date != order.biz_date:
            await assert_not_locked(db, site_id=order.site_id, rider_id=old_rider_id, biz_date=old_biz_date)
        await db.flush()
        rider_ids = {old_rider_id, order.rider_id}
        date_from = min(old_biz_date, order.biz_date)
        date_to = max(old_biz_date, order.biz_date)
        await mark_stale(db, rider_ids=rider_ids, date_from=date_from, date_to=date_to)
        await audit_service.record(
            db,
            request,
            module='订单明细',
            action='订单纠错',
            target_type='order',
            target_id=order.id,
            target_label=f'订单{order.order_no}',
            reason=obj.reason,
            before=before,
            after=order_snapshot(order),
        )
        details = await _to_details(db, [order])
        return details[0]

    @staticmethod
    async def delete(*, db: AsyncSession, request: Request, pk: int, reason: str) -> None:
        """
        删除订单

        :param db: 数据库会话
        :param request: 请求对象
        :param pk: 订单 ID
        :param reason: 原因
        :return:
        """
        if not reason or not reason.strip():
            raise errors.RequestError(msg='请填写操作原因')
        order = await order_dao.get(db, pk)
        if order is None:
            raise errors.NotFoundError(msg='订单不存在')
        visible = await get_visible_site_ids(request, db)
        assert_site_visible(visible, order.site_id)
        if order.is_locked:
            raise errors.ForbiddenError(msg='该日期所属结算周期已锁账，禁止修改，请走反冲补发流程')
        await assert_not_locked(db, site_id=order.site_id, rider_id=order.rider_id, biz_date=order.biz_date)
        before = order_snapshot(order)
        label = f'订单{order.order_no}'
        rider_id = order.rider_id
        biz_date = order.biz_date
        order_id = order.id
        count = await order_dao.delete(db, pk)
        if count <= 0:
            raise errors.NotFoundError(msg='订单不存在')
        await mark_stale(db, rider_ids=[rider_id], date_from=biz_date, date_to=biz_date)
        await audit_service.record(
            db,
            request,
            module='订单明细',
            action='删除订单',
            target_type='order',
            target_id=order_id,
            target_label=label,
            reason=reason.strip(),
            before=before,
        )


async def _get_site(db: AsyncSession, site_id: int) -> RiderSalarySite:
    site = await db.scalar(select(RiderSalarySite).where(RiderSalarySite.id == site_id, RiderSalarySite.deleted == 0))
    if site is None:
        raise errors.NotFoundError(msg='站点不存在')
    return site


async def _get_rider(db: AsyncSession, rider_id: int) -> RiderSalaryRider:
    rider = await db.scalar(
        select(RiderSalaryRider).where(RiderSalaryRider.id == rider_id, RiderSalaryRider.deleted == 0)
    )
    if rider is None:
        raise errors.NotFoundError(msg='骑手不存在')
    return rider


async def _to_details(db: AsyncSession, orders: Sequence[Any]) -> list[GetOrderDetail]:
    model_orders = [item for item in orders if isinstance(item, RiderSalaryOrder)]
    if len(model_orders) != len(orders) and orders:
        ids: list[int] = []
        for item in orders:
            if isinstance(item, RiderSalaryOrder):
                ids.append(item.id)
            elif isinstance(item, dict):
                ids.append(int(item['id']))
            else:
                ids.append(int(item.id))
        result = await db.scalars(select(RiderSalaryOrder).where(RiderSalaryOrder.id.in_(ids)))
        by_id = {item.id: item for item in result.all()}
        model_orders = [by_id[pk] for pk in ids if pk in by_id]
    if not model_orders:
        return []
    rider_ids = {item.rider_id for item in model_orders}
    site_ids = {item.site_id for item in model_orders}
    riders = {
        item.id: item
        for item in (await db.scalars(select(RiderSalaryRider).where(RiderSalaryRider.id.in_(rider_ids)))).all()
    }
    sites = {
        item.id: item
        for item in (await db.scalars(select(RiderSalarySite).where(RiderSalarySite.id.in_(site_ids)))).all()
    }
    details: list[GetOrderDetail] = []
    for order in model_orders:
        rider = riders.get(order.rider_id)
        site = sites.get(order.site_id)
        detail = GetOrderDetail.model_validate(order)
        details.append(
            detail.model_copy(
                update={
                    'rider_job_no': rider.job_no if rider else '',
                    'rider_name': rider.name if rider else '',
                    'site_name': site.name if site else '',
                    'status_label': order_status_label(order.status),
                    'source_label': order_source_label(order.source),
                }
            )
        )
    return details


order_service: OrderService = OrderService()

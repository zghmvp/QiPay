from collections.abc import Sequence
from datetime import date

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.utils.order_attention import order_attention_condition
from backend.utils.timezone import timezone


class CRUDOrder(CRUDPlus[RiderSalaryOrder]):
    """订单明细数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> RiderSalaryOrder | None:
        """
        获取订单

        :param db: 数据库会话
        :param pk: 订单 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_by_order_no(self, db: AsyncSession, order_no: str) -> RiderSalaryOrder | None:
        """
        按订单号获取未删除订单

        :param db: 数据库会话
        :param order_no: 订单号
        :return:
        """
        return await self.select_model_by_column(db, order_no=order_no, deleted=0)

    async def get_existing_order_nos(self, db: AsyncSession, order_nos: Sequence[str]) -> set[str]:
        """
        查询库中已存在的订单号

        :param db: 数据库会话
        :param order_nos: 订单号列表
        :return:
        """
        nos = [item for item in order_nos if item]
        if not nos:
            return set()
        rows = await db.scalars(
            select(RiderSalaryOrder.order_no).where(
                RiderSalaryOrder.order_no.in_(nos),
                RiderSalaryOrder.deleted == 0,
            )
        )
        return set(rows.all())

    @staticmethod
    def _list_filters(
        *,
        site_ids: set[int] | None,
        site_id: int | None,
        rider_id: int | None,
        date_from: date | None,
        date_to: date | None,
        status: str | None,
        order_no: str | None,
        import_batch_id: int | None,
        is_locked: bool | None,
        attention: bool | None,
    ) -> dict:
        """组装订单列表等值/范围过滤条件。"""
        filters: dict = {'deleted': 0}
        if site_ids is not None:
            filters['site_id__in'] = list(site_ids) if site_ids else [0]
        if site_id is not None:
            filters['site_id'] = site_id
        if rider_id is not None:
            filters['rider_id'] = rider_id
        if date_from is not None:
            filters['biz_date__ge'] = date_from
        if date_to is not None:
            filters['biz_date__le'] = date_to
        # attention 与单状态互斥：需关注时不再按 status 精确匹配
        if status is not None and not attention:
            filters['status'] = status
        if order_no is not None:
            filters['order_no__like'] = f'%{order_no}%'
        if import_batch_id is not None:
            filters['import_batch_id'] = import_batch_id
        if is_locked is not None:
            filters['is_locked'] = is_locked
        return filters

    async def get_select(
        self,
        *,
        site_ids: set[int] | None,
        site_id: int | None,
        rider_id: int | None,
        date_from: date | None,
        date_to: date | None,
        status: str | None,
        order_no: str | None,
        import_batch_id: int | None,
        is_locked: bool | None,
        attention: bool | None = None,
    ) -> Select:
        """
        订单分页查询

        :param site_ids: 可见站点，None 表示全部
        :param site_id: 站点筛选
        :param rider_id: 骑手筛选
        :param date_from: 业务日期起
        :param date_to: 业务日期止
        :param status: 订单状态
        :param order_no: 订单号
        :param import_batch_id: 导入批次
        :param is_locked: 是否锁账
        :param attention: 需关注（异常∪退款∪超时>60min，与工作台同源）
        :return:
        """
        filters = self._list_filters(
            site_ids=site_ids,
            site_id=site_id,
            rider_id=rider_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
            order_no=order_no,
            import_batch_id=import_batch_id,
            is_locked=is_locked,
            attention=attention,
        )
        stmt = await self.select_order('id', 'desc', **filters)
        if attention:
            stmt = stmt.where(order_attention_condition())
        return stmt

    async def delete(self, db: AsyncSession, pk: int) -> int:
        """
        逻辑删除订单

        :param db: 数据库会话
        :param pk: 订单 ID
        :return:
        """
        return await self.delete_model_by_column(
            db,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now(),
            id=pk,
            deleted=0,
        )


order_dao: CRUDOrder = CRUDOrder(RiderSalaryOrder)

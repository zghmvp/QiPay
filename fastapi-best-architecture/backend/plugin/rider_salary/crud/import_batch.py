from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.import_batch import RiderSalaryImportBatch


class CRUDImportBatch(CRUDPlus[RiderSalaryImportBatch]):
    """导入批次数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> RiderSalaryImportBatch | None:
        """
        获取导入批次

        :param db: 数据库会话
        :param pk: 批次 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_select(
        self,
        *,
        site_ids: set[int] | None,
        site_id: int | None,
        status: str | None,
    ) -> Select:
        """
        导入批次分页查询

        :param site_ids: 可见站点，None 表示全部
        :param site_id: 站点筛选
        :param status: 批次状态
        :return:
        """
        filters: dict = {'deleted': 0}
        if site_ids is not None:
            filters['site_id__in'] = list(site_ids) if site_ids else [0]
        if site_id is not None:
            filters['site_id'] = site_id
        if status is not None:
            filters['status'] = status
        return await self.select_order('id', 'desc', **filters)


import_batch_dao: CRUDImportBatch = CRUDImportBatch(RiderSalaryImportBatch)

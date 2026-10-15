from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.advance_policy import RiderSalaryAdvancePolicy


class CRUDAdvancePolicy(CRUDPlus[RiderSalaryAdvancePolicy]):
    """预支规则数据库操作"""

    async def get_by_site(self, db: AsyncSession, site_id: int) -> RiderSalaryAdvancePolicy | None:
        """按站点读取未删除规则，site_id 为 0 表示全局。"""
        return await self.select_model_by_column(db, site_id=site_id, deleted=0)


advance_policy_dao: CRUDAdvancePolicy = CRUDAdvancePolicy(RiderSalaryAdvancePolicy)

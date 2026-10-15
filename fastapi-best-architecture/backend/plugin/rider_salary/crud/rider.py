from collections.abc import Sequence
from datetime import date

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.app.admin.model import User
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.schema.rider import CreateRiderParam, UpdateRiderParam
from backend.utils.timezone import timezone


class CRUDRider(CRUDPlus[RiderSalaryRider]):
    """骑手数据库操作"""

    async def get(self, db: AsyncSession, pk: int) -> RiderSalaryRider | None:
        """
        获取骑手

        :param db: 数据库会话
        :param pk: 骑手 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_by_job_no(self, db: AsyncSession, job_no: str) -> RiderSalaryRider | None:
        """
        按工号获取骑手

        :param db: 数据库会话
        :param job_no: 工号
        :return:
        """
        return await self.select_model_by_column(db, job_no=job_no, deleted=0)

    async def get_on_job_ids_by_site(self, db: AsyncSession, site_id: int) -> Sequence[int]:
        """
        获取站点在职骑手 ID

        :param db: 数据库会话
        :param site_id: 站点 ID
        :return:
        """
        rows = await self.select_models(db, site_id=site_id, status='on_job', deleted=0)
        return [row.id for row in rows]

    async def count_by_site(self, db: AsyncSession, site_id: int) -> int:
        """
        统计站点下骑手数

        :param db: 数据库会话
        :param site_id: 站点 ID
        :return:
        """
        rows = await self.select_models(db, site_id=site_id, deleted=0)
        return len(rows)

    async def get_select(
        self,
        site_id: int | None,
        status: str | None,
        employ_type: str | None,
        keyword: str | None,
        site_ids: set[int] | None,
        phone: str | None = None,
        hire_date_from: date | None = None,
        hire_date_to: date | None = None,
        account_status: str | None = None,
        settle_cycle_override: str | None = None,
    ) -> Select:
        """
        骑手列表查询

        :param site_id: 站点 ID
        :param status: 状态
        :param employ_type: 用工类型
        :param keyword: 工号或姓名
        :param site_ids: 可见站点，None 表示全部
        :param phone: 手机号
        :param hire_date_from: 入职日期起
        :param hire_date_to: 入职日期止
        :param account_status: 账号状态，none 未开通，0 停用，1 启用
        :param settle_cycle_override: 结算周期覆盖，inherit 表示跟随站点
        :return:
        """
        filters: dict = {'deleted': 0}
        if site_id is not None:
            filters['site_id'] = site_id
        if status:
            filters['status'] = status
        if employ_type:
            filters['employ_type'] = employ_type
        if site_ids is not None:
            filters['site_id__in'] = list(site_ids) or [-1]
        clauses = []
        if keyword:
            like = f'%{keyword}%'
            clauses.append(or_(self.model.job_no.like(like), self.model.name.like(like)))
        if phone:
            clauses.append(self.model.phone.like(f'%{phone}%'))
        if hire_date_from is not None:
            clauses.append(self.model.hire_date >= hire_date_from)
        if hire_date_to is not None:
            clauses.append(self.model.hire_date <= hire_date_to)
        if account_status == 'none':
            clauses.append(self.model.user_id.is_(None))
        elif account_status in {'0', '1'}:
            clauses.append(
                self.model.user_id.in_(select(User.id).where(User.status == int(account_status), User.deleted == 0))
            )
        if settle_cycle_override == 'inherit':
            clauses.append(self.model.settle_cycle_override.is_(None))
        elif settle_cycle_override:
            filters['settle_cycle_override'] = settle_cycle_override
        if clauses:
            return await self.select_order('id', 'desc', and_(*clauses), **filters)
        return await self.select_order('id', 'desc', **filters)

    async def create(self, db: AsyncSession, obj: CreateRiderParam) -> RiderSalaryRider:
        """
        创建骑手

        :param db: 数据库会话
        :param obj: 创建参数
        :return:
        """
        return await self.create_model(db, obj, flush=True)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateRiderParam, **kwargs) -> int:
        """
        更新骑手

        :param db: 数据库会话
        :param pk: 骑手 ID
        :param obj: 更新参数
        :return:
        """
        payload = obj.model_dump(exclude_unset=True, exclude={'reason', 'transfer_date'})
        payload.update(kwargs)
        return await self.update_model_by_column(db, payload, id=pk, deleted=0)

    async def delete(self, db: AsyncSession, pk: int) -> int:
        """
        逻辑删除骑手

        :param db: 数据库会话
        :param pk: 骑手 ID
        :return:
        """
        return await self.delete_model_by_column(
            db,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now,
            id=pk,
            deleted=0,
        )


rider_dao: CRUDRider = CRUDRider(RiderSalaryRider)

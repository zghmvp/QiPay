from sqlalchemy import Select
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.rider_salary.model.audit_log import RiderSalaryAuditLog


class CRUDAuditLog(CRUDPlus[RiderSalaryAuditLog]):
    """操作日志数据库操作"""

    async def get_select(
        self,
        module: str | None,
        action: str | None,
        operator: str | None,
        date_from: str | None,
        date_to: str | None,
        target_type: str | None,
        keyword: str | None,
    ) -> Select:
        """
        操作日志列表查询

        :param module: 模块
        :param action: 动作
        :param operator: 操作人
        :param date_from: 开始时间
        :param date_to: 结束时间
        :param target_type: 对象类型
        :param keyword: 关键字
        :return:
        """
        filters: dict = {}
        if module:
            filters['module'] = module
        if action:
            filters['action'] = action
        if operator:
            if operator.isdigit():
                filters['operator_id'] = int(operator)
            else:
                filters['operator_name__like'] = f'%{operator}%'
        if date_from:
            filters['operate_time__ge'] = date_from
        if date_to:
            filters['operate_time__le'] = date_to
        if target_type:
            filters['target_type'] = target_type
        if keyword:
            filters['description__like'] = f'%{keyword}%'
        return await self.select_order('operate_time', 'desc', **filters)


audit_log_dao: CRUDAuditLog = CRUDAuditLog(RiderSalaryAuditLog)

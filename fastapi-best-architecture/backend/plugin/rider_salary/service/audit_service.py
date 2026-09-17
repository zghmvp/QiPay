from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.pagination import paging_data
from backend.plugin.rider_salary.crud.audit_log import audit_log_dao
from backend.plugin.rider_salary.utils.audit import audit_service as _audit_writer
from backend.plugin.rider_salary.utils.deps import get_visible_site_ids


def snapshot(obj: object, fields: tuple[str, ...]) -> dict[str, Any]:
    """
    将模型指定字段转为可写入 JSON 的字典

    :param obj: 模型对象
    :param fields: 字段名
    :return:
    """
    data: dict[str, Any] = {}
    for name in fields:
        value = getattr(obj, name, None)
        if isinstance(value, date):
            data[name] = value.isoformat()
        elif isinstance(value, Decimal):
            data[name] = str(value)
        else:
            data[name] = value
    return data


def is_global_operator(request: Request) -> bool:
    """
    是否为超管或薪资管理员

    :param request: 请求对象
    :return:
    """
    user = request.user
    if getattr(user, 'is_superuser', False):
        return True
    roles = getattr(user, 'roles', None) or []
    return '薪资管理员' in {getattr(role, 'name', None) for role in roles}


class AuditService:
    """业务审计日志服务"""

    @staticmethod
    async def record(
        db: AsyncSession,
        request: Request,
        *,
        module: str,
        action: str,
        target_type: str,
        target_id: int | str | None,
        target_label: str,
        site_id: int | None,
        reason: str | None = None,
        before: dict | None = None,
        after: dict | None = None,
        description: str | None = None,
    ) -> None:
        """写入业务审计日志"""
        await _audit_writer.record(
            db,
            request,
            module=module,
            action=action,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            site_id=site_id,
            reason=reason,
            before=before,
            after=after,
            description=description,
        )

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        request: Request,
        module: str | None,
        action: str | None,
        operator: str | None,
        date_from: str | None,
        date_to: str | None,
        target_type: str | None,
        keyword: str | None,
    ) -> dict[str, Any]:
        """
        分页获取操作日志

        :param db: 数据库会话
        :param request: 请求对象
        :param module: 模块
        :param action: 动作
        :param operator: 操作人
        :param date_from: 开始时间
        :param date_to: 结束时间
        :param target_type: 对象类型
        :param keyword: 关键字
        :return:
        """
        visible = await get_visible_site_ids(request, db)
        stmt = await audit_log_dao.get_select(
            module=module,
            action=action,
            operator=operator,
            date_from=date_from,
            date_to=date_to,
            target_type=target_type,
            keyword=keyword,
            site_ids=visible,
        )
        return await paging_data(db, stmt)


audit_service: AuditService = AuditService()

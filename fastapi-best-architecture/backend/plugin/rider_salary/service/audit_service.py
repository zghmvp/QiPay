import json

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.pagination import paging_data
from backend.plugin.rider_salary.crud.audit_log import audit_log_dao
from backend.plugin.rider_salary.utils.audit import audit_service as _audit_writer
from backend.plugin.rider_salary.utils.audit import mask_audit_phones
from backend.plugin.rider_salary.utils.deps import get_visible_site_ids
from backend.plugin.rider_salary.utils.excel import assert_export_row_limit, count_statement, write_workbook
from backend.plugin.rider_salary.utils.scope import sees_all_sites

AUDIT_EXPORT_HEADERS = [
    '操作时间',
    '操作人',
    '模块',
    '动作',
    '对象类型',
    '对象编号',
    '对象摘要',
    '站点',
    '原因',
    '描述',
    '变更前',
    '变更后',
]


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
    是否为超管或持有全站可见权限码

    :param request: 请求对象
    :return:
    """
    return sees_all_sites(request.user)


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
        reason: str | None = None,
        before: dict | None = None,
        after: dict | None = None,
        description: str | None = None,
        site_id: int | None = None,
    ) -> None:
        """
        写入业务审计日志

        :param db: 数据库会话
        :param request: 请求对象
        :param module: 模块
        :param action: 动作
        :param target_type: 对象类型
        :param target_id: 对象 ID
        :param target_label: 对象摘要
        :param reason: 原因
        :param before: 变更前
        :param after: 变更后
        :param description: 自然语言描述
        :param site_id: 站点 ID。传入后不再回查；省略时按对象类型回填
        :return:
        """
        await _audit_writer.record(
            db,
            request,
            module=module,
            action=action,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            reason=reason,
            before=before,
            after=after,
            description=description,
            site_id=site_id,
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

        全站可见（超管或 ``rs:scope:all``）看全部，并保留快照里的手机号。
        其余用户只看 ``site_id`` 落在可见站点内的记录；站点为空的全局对象不可见，手机号中间 4 位打码。

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
        page = await paging_data(db, stmt)
        items = [_audit_row_dict(item) for item in page.get('items') or []]
        if visible is not None:
            items = [mask_audit_phones(item) for item in items]
        page['items'] = items
        return page

    @staticmethod
    async def export(
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
    ) -> bytes:
        """
        导出操作日志

        筛选和站点范围与列表相同。站点负责人看不到全局对象，手机号中间 4 位打码。

        :param db: 数据库会话
        :param request: 请求对象
        :param module: 模块
        :param action: 动作
        :param operator: 操作人
        :param date_from: 开始时间
        :param date_to: 结束时间
        :param target_type: 对象类型
        :param keyword: 关键字
        :return: xlsx 字节
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
        total = await count_statement(db, stmt)
        assert_export_row_limit(total)
        rows = list((await db.scalars(stmt)).all())
        mask = visible is not None
        data_rows = []
        for row in rows:
            item = _audit_row_dict(row)
            if mask:
                item = mask_audit_phones(item)
            data_rows.append(audit_export_cells(item))
        return write_workbook([('操作日志', AUDIT_EXPORT_HEADERS, data_rows)])


def audit_export_cells(item: dict[str, Any]) -> list[Any]:
    """把一条操作日志转成导出单元格。变更前后写成 JSON 文本。"""
    operate_time = item.get('operate_time')
    if isinstance(operate_time, datetime):
        operate_time = operate_time.isoformat(sep=' ', timespec='seconds')
    site_id = item.get('site_id')
    return [
        '' if operate_time is None else operate_time,
        item.get('operator_name') or '',
        item.get('module') or '',
        item.get('action') or '',
        item.get('target_type') or '',
        item.get('target_id') or '',
        item.get('target_label') or '',
        '' if site_id is None else site_id,
        item.get('reason') or '',
        item.get('description') or '',
        _json_cell(item.get('before')),
        _json_cell(item.get('after')),
    ]


def _json_cell(value: Any) -> str:
    if not value:
        return ''
    return json.dumps(value, ensure_ascii=False, default=str)


def _audit_row_dict(item: Any) -> dict[str, Any]:
    """分页结果可能是字典，也可能是尚未序列化的模型。打码前先复制成字典，避免改到会话里的原对象。"""
    if isinstance(item, dict):
        return item
    mapper = getattr(item, '__mapper__', None)
    if mapper is None:
        return item
    return {column.key: getattr(item, column.key) for column in mapper.column_attrs}


audit_service: AuditService = AuditService()

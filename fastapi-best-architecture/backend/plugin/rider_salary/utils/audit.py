import re

from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.context import ctx
from backend.common.exception import errors
from backend.plugin.rider_salary.model.audit_log import RiderSalaryAuditLog
from backend.utils.timezone import timezone
from backend.utils.trace_id import get_request_trace_id

# FBA 测试种子把 admin.nickname 写成「用户88888」，不算有效展示名
_PLACEHOLDER_NICKNAME = re.compile(r'^用户\d+$')

REASON_REQUIRED_ACTIONS = frozenset({
    '订单纠错',
    '奖惩修改',
    '奖惩删除',
    '锁账',
    '反冲补发',
    '方案停用',
    '方案回退',
    '预支驳回',
    '预支取消',
    '开通骑手账号',
    '停用骑手账号',
    'order_correct',
    'adjustment_edit',
    'adjustment_delete',
    'period_lock',
    'period_reverse',
    'plan_disable',
    'plan_rollback',
    'advance_reject',
    'advance_cancel',
    'rider_open_account',
    'rider_disable_account',
})


def require_reason(action: str, reason: str | None) -> None:
    """
    校验必填操作原因

    :param action: 动作
    :param reason: 原因
    :return:
    """
    if action in REASON_REQUIRED_ACTIONS and not (reason and reason.strip()):
        raise errors.RequestError(msg='请填写操作原因')


def _user_attr(user: object, *names: str) -> str | None:
    if user is None:
        return None
    dumped: dict[str, Any] | None = None
    for name in names:
        value = None
        if isinstance(user, dict):
            value = user.get(name)
        else:
            value = getattr(user, name, None)
            if value is None and hasattr(user, 'model_dump'):
                if dumped is None:
                    dumped = user.model_dump()
                value = dumped.get(name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _operator_name(request: Request) -> str:
    """优先 nickname，其次 username；FBA 占位昵称「用户数字」视为缺失。"""
    user = getattr(request, 'user', None)
    nickname = _user_attr(user, 'nickname', 'nick_name')
    if nickname and not _PLACEHOLDER_NICKNAME.fullmatch(nickname):
        return nickname
    username = _user_attr(user, 'username', 'user_name')
    if username:
        return username
    if nickname:
        return nickname
    return '未知'


def _operator_id(request: Request) -> int:
    user = getattr(request, 'user', None)
    if isinstance(user, dict):
        return int(user.get('id') or 0)
    return int(getattr(user, 'id', 0) or 0)


def _client_ip(request: Request) -> str | None:
    state_ip = getattr(request.state, 'ip', None)
    if state_ip:
        return str(state_ip)
    if ctx.exists():
        ctx_ip = getattr(ctx, 'ip', None)
        if ctx_ip:
            return str(ctx_ip)
    if request.client is not None:
        return request.client.host
    return None


def _format_time(operate_time: datetime) -> str:
    return timezone.to_str(operate_time)


def build_description(
    *,
    operator_name: str,
    operate_time: datetime,
    target_label: str,
    action: str,
    reason: str | None,
) -> str:
    """按模板生成审计描述"""
    text = f'{operator_name} 于 {_format_time(operate_time)} 对 {target_label} 执行了 {action}'
    if reason and reason.strip():
        return f'{text}，原因：{reason.strip()}'
    return text


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
        :return:
        """
        require_reason(action, reason)
        operate_time = timezone.now()
        operator_name = _operator_name(request)
        text = description or build_description(
            operator_name=operator_name,
            operate_time=operate_time,
            target_label=target_label,
            action=action,
            reason=reason,
        )
        target_id_text = None if target_id is None else str(target_id)
        db.add(
            RiderSalaryAuditLog(
                operator_id=_operator_id(request),
                operator_name=operator_name,
                operate_time=operate_time,
                module=module,
                action=action,
                target_type=target_type,
                target_label=target_label,
                target_id=target_id_text,
                reason=reason,
                before=before,
                after=after,
                description=text,
                ip=_client_ip(request),
                trace_id=get_request_trace_id(),
            )
        )


audit_service = AuditService()

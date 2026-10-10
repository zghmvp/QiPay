"""读接口过渡期权限：同时接受 view 码和原写码。"""

from fastapi import Request
from starlette.authentication import UnauthenticatedUser

from backend.common.context import ctx
from backend.common.enums import StatusType
from backend.common.exception import errors
from backend.core.conf import settings


def choose_granted_permission(request: Request, values: tuple[str, ...]) -> str:
    """挑出当前用户实际拥有的第一个权限码。都没有时返回第一个，交给 RBAC 拒绝。

    :param request: 当前请求
    :param values: 按优先级排列的权限码，调用方把 view 码放在前面
    :return: 写入上下文的权限码
    """
    user = getattr(request, 'user', None)
    if user is None or isinstance(user, UnauthenticatedUser) or getattr(user, 'is_superuser', False):
        return values[0]
    granted: set[str] = set()
    for role in getattr(user, 'roles', None) or []:
        if getattr(role, 'status', None) != StatusType.enable:
            continue
        for menu in getattr(role, 'menus', None) or []:
            if menu is None or getattr(menu, 'status', None) != StatusType.enable:
                continue
            perms = getattr(menu, 'perms', None)
            if perms:
                granted.update(perms.split(','))
    for value in values:
        if value in granted:
            return value
    return values[0]


class RequestAnyPermission:
    """插件内的多码读权限。不修改框架 RequestPermission。

    过渡期内 GET 接受新的 view 码或原来的写码之一。这里只把用户拥有的那个码
    写入 ctx.permission，是否放行仍由随后的 DependsRBAC 判定。
    """

    def __init__(self, *values: str) -> None:
        """
        :param values: 权限码，view 码在前，原写码在后
        """
        self.values = values

    async def __call__(self, request: Request) -> None:
        """按角色菜单选择一个权限码交给 RBAC。

        :param request: 当前请求
        """
        if not settings.RBAC_ROLE_MENU_MODE:
            return
        if not self.values or any(not isinstance(value, str) or not value for value in self.values):
            raise errors.ServerError
        ctx.permission = choose_granted_permission(request, self.values)

"""读权限过渡期：view 码优先，没有时回落到原写码。"""

import anyio

from starlette.authentication import UnauthenticatedUser
from starlette_context import request_cycle_context

from backend.common.context import ctx
from backend.common.enums import StatusType
from backend.core.conf import settings
from backend.plugin.rider_salary.utils.permission import RequestAnyPermission, choose_granted_permission


class _Menu:
    def __init__(self, perms: str | None, status: int = StatusType.enable) -> None:
        self.perms = perms
        self.status = status


class _Role:
    def __init__(self, menus: list[_Menu | None], status: int = StatusType.enable) -> None:
        self.menus = menus
        self.status = status


class _User:
    def __init__(self, roles: list[_Role], *, is_superuser: bool = False) -> None:
        self.roles = roles
        self.is_superuser = is_superuser


class _Request:
    def __init__(self, user: object) -> None:
        self.user = user


def test_choose_prefers_view_then_legacy_then_denies() -> None:
    """同时拥有时用 view；只有旧写码时用旧码；都没有时仍写下 view，让 RBAC 拒绝。"""
    view_and_write = _Request(_User([_Role([_Menu('rs:rider:add'), _Menu('rs:rider:view')])]))
    assert choose_granted_permission(view_and_write, ('rs:rider:view', 'rs:rider:add')) == 'rs:rider:view'

    legacy_only = _Request(_User([_Role([_Menu('rs:rider:add')])]))
    assert choose_granted_permission(legacy_only, ('rs:rider:view', 'rs:rider:add')) == 'rs:rider:add'

    neither = _Request(_User([_Role([_Menu('rs:notice:add')])]))
    assert choose_granted_permission(neither, ('rs:rider:view', 'rs:rider:add')) == 'rs:rider:view'


def test_choose_ignores_disabled_role_menu_and_blank() -> None:
    """停用角色、停用菜单和空权限不参与匹配；逗号分隔的 perms 按段匹配。"""
    request = _Request(
        _User([
            _Role([_Menu('rs:rider:view')], status=StatusType.disable),
            _Role([_Menu('rs:rider:add', status=StatusType.disable), None, _Menu(None)]),
            _Role([_Menu('rs:adjustment:view,rs:rider:add')]),
        ])
    )
    assert choose_granted_permission(request, ('rs:rider:view', 'rs:rider:add')) == 'rs:rider:add'


def test_superuser_uses_view_code() -> None:
    """超管不看菜单，直接采用排在前面的 view 码。"""
    request = _Request(_User([], is_superuser=True))
    assert choose_granted_permission(request, ('rs:notice:view', 'rs:notice:add')) == 'rs:notice:view'


def test_request_any_permission_writes_chosen_code() -> None:
    """依赖把选中的码写入上下文，供随后的 DependsRBAC 校验。"""

    async def _run() -> None:
        with request_cycle_context({}):
            dep = RequestAnyPermission('rs:dayflag:view', 'rs:dayflag:edit')
            await dep(_Request(_User([_Role([_Menu('rs:dayflag:edit')])])))
            assert ctx.permission == 'rs:dayflag:edit'

    anyio.run(_run)


def test_request_any_permission_skips_casbin_mode() -> None:
    """非菜单 RBAC 模式不改写上下文，避免干扰 casbin。"""

    async def _run() -> None:
        with request_cycle_context({}):
            ctx.permission = 'keep'
            previous = settings.RBAC_ROLE_MENU_MODE
            settings.RBAC_ROLE_MENU_MODE = False
            try:
                dep = RequestAnyPermission('rs:notice:view', 'rs:notice:add')
                await dep(_Request(_User([_Role([_Menu('rs:notice:view')])])))
                assert ctx.permission == 'keep'
            finally:
                settings.RBAC_ROLE_MENU_MODE = previous

    anyio.run(_run)


def test_unauthenticated_user_falls_back_to_view_code() -> None:
    """未登录时不读角色，留下 view 码给后续 JWT 校验。"""
    request = _Request(UnauthenticatedUser())
    assert choose_granted_permission(request, ('rs:advance:view', 'rs:advance:approve')) == 'rs:advance:view'

"""权限饱和目录的无库解析工具（SQL 种子 + api/v1 依赖合同）。"""

from __future__ import annotations

import ast
import re

from dataclasses import dataclass
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SQL_ROOT = PLUGIN_ROOT / 'sql'
API_V1 = PLUGIN_ROOT / 'api' / 'v1'
ROUTER_FILE = PLUGIN_ROOT / 'api' / 'router.py'

SNOWFLAKE_OFFSET = 2_060_000_000_000_000_000

ROLE_SALARY_ADMIN = 92001
ROLE_SITE_OWNER = 92002
ROLE_SITE_DEPUTY = 92003
ROLE_RIDER = 92004

SA_ONLY_PAGES = frozenset({91002, 91006})
SA_ONLY_BUTTONS = frozenset({
    91101,
    91102,
    91103,
    91104,
    91110,
    91111,
    91112,
    91113,
    91114,
    91115,
    91116,
    91117,
    91118,
    91119,
    91120,
    91135,
})
ROLLBACK_BUTTON = 91121
REVERSE_BUTTON = 91135
ACCOUNT_BUTTON = 91110
PERIOD_DELETE_PERM = 'rs:period:delete'
PAYROLL_VIEW_PERM = 'rs:payroll:view'

REQUIRED_SEED_PERMS = frozenset({
    'rs:site:add',
    'rs:site:edit',
    'rs:site:del',
    'rs:site:manager',
    'rs:rider:add',
    'rs:rider:edit',
    'rs:rider:del',
    'rs:rider:binding',
    'rs:rider:employ',
    'rs:rider:account',
    'rs:subject:add',
    'rs:subject:edit',
    'rs:subject:del',
    'rs:plan:add',
    'rs:plan:edit',
    'rs:plan:del',
    'rs:plan:trial',
    'rs:plan:activate',
    'rs:plan:disable',
    'rs:plan:copy',
    'rs:plan:rollback',
    'rs:order:add',
    'rs:order:edit',
    'rs:order:del',
    'rs:order:import',
    'rs:order:export',
    'rs:adjustment:add',
    'rs:adjustment:edit',
    'rs:adjustment:del',
    'rs:period:generate',
    'rs:period:calculate',
    'rs:period:lock',
    'rs:period:mark-paid',
    'rs:period:reverse',
    'rs:period:export',
    'rs:period:delete',
    'rs:payroll:view',
    'rs:calendar:view',
    'rs:dashboard:view',
    'rs:advance:approve',
    'rs:advance:reject',
    'rs:advance:mark-paid',
    'rs:advance:cancel',
    'rs:advance:export',
    'rs:audit:view',
})

# 历史 JWT-only 管理端（订单/批次/引擎）已补 DependsRBAC；仅 /me/* 可只挂 JWT。
JWT_ONLY_OBSERVATION = frozenset()

WRITE_LIKE_ACTIONS = frozenset({
    'add',
    'edit',
    'del',
    'delete',
    'approve',
    'import',
    'generate',
    'calculate',
    'lock',
    'reverse',
    'trial',
    'activate',
    'disable',
    'copy',
    'rollback',
    'manager',
    'account',
    'mark-paid',
    'reject',
    'cancel',
})

# 合同快照：当前代码读接口仍挂写权限（修复后改断言）
# GET /riders 列表已不再挂 add；日标记/公告 API 已裁剪。
READ_HUNG_ON_WRITE_SNAPSHOT = {
    ('GET', '/riders/{pk}'): 'rs:rider:add',
    ('GET', '/adjustments'): 'rs:adjustment:add',
    ('GET', '/adjustments/{pk}'): 'rs:adjustment:add',
    ('GET', '/advances'): 'rs:advance:approve',
    ('GET', '/advances/{pk}'): 'rs:advance:approve',
    ('GET', '/orders/import-template'): 'rs:order:import',
    ('GET', '/import-batches/{pk}/error-report'): 'rs:order:import',
    ('GET', '/recalc-jobs/{pk}'): 'rs:period:calculate',
    ('GET', '/plan-versions/{pk}/rollback-preview'): 'rs:plan:rollback',
}


def canon_id(value: int) -> int:
    """把雪花种子 ID 折回自增段。"""
    if value >= SNOWFLAKE_OFFSET:
        return int(value - SNOWFLAKE_OFFSET)
    return int(value)


def init_sql_files() -> list[Path]:
    return sorted(SQL_ROOT.glob('*/init*.sql'))


def _extract_insert_block(sql: str, table: str) -> str:
    pattern = re.compile(
        rf'insert\s+into\s+{table}\b.*?\nvalues\s*(.*?);',
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(sql)
    if not match:
        raise AssertionError(f'未找到 insert into {table}')
    return match.group(1)


def _split_value_rows(block: str) -> list[str]:
    rows: list[str] = []
    depth = 0
    start: int | None = None
    for idx, char in enumerate(block):
        if char == '(':
            if depth == 0:
                start = idx
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0 and start is not None:
                rows.append(block[start + 1 : idx])
                start = None
    return rows


def _split_sql_args(row: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    in_quote = False
    i = 0
    while i < len(row):
        char = row[i]
        if char == "'" and not in_quote:
            in_quote = True
            buf.append(char)
        elif char == "'" and in_quote:
            if i + 1 < len(row) and row[i + 1] == "'":
                buf.append("''")
                i += 1
            else:
                in_quote = False
                buf.append(char)
        elif char == ',' and not in_quote:
            parts.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(char)
        i += 1
    if buf:
        parts.append(''.join(buf).strip())
    return parts


def _unquote(token: str) -> str | None:
    if token.lower() == 'null':
        return None
    if token.startswith("'") and token.endswith("'"):
        return token[1:-1].replace("''", "'")
    return token


@dataclass(frozen=True)
class SeedMenu:
    id: int
    title: str
    menu_type: int
    perms: str | None
    parent_id: int | None


@dataclass(frozen=True)
class SeedRole:
    id: int
    name: str


def parse_seed(sql_text: str) -> tuple[dict[int, SeedMenu], dict[int, SeedRole], dict[int, set[int]]]:
    """解析一份 init*.sql 的菜单 / 角色 / 角色菜单。"""
    menus: dict[int, SeedMenu] = {}
    for block in re.finditer(
        r'insert\s+into\s+sys_menu\b.*?\nvalues\s*(.*?);',
        sql_text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        for raw in _split_value_rows(block.group(1)):
            args = _split_sql_args(raw)
            if len(args) < 15:
                continue
            menu_id = canon_id(int(args[0]))
            title = _unquote(args[1]) or ''
            menu_type = int(args[6])
            perms = _unquote(args[8])
            parent_raw = args[14]
            parent_id = None if parent_raw.lower() == 'null' else canon_id(int(parent_raw))
            menus[menu_id] = SeedMenu(menu_id, title, menu_type, perms, parent_id)

    roles: dict[int, SeedRole] = {}
    role_block = _extract_insert_block(sql_text, 'sys_role')
    for raw in _split_value_rows(role_block):
        args = _split_sql_args(raw)
        role_id = canon_id(int(args[0]))
        name = _unquote(args[1]) or ''
        roles[role_id] = SeedRole(role_id, name)

    bindings: dict[int, set[int]] = {
        ROLE_SALARY_ADMIN: set(),
        ROLE_SITE_OWNER: set(),
        ROLE_SITE_DEPUTY: set(),
        ROLE_RIDER: set(),
    }
    role_menu_block = _extract_insert_block(sql_text, 'sys_role_menu')
    for raw in _split_value_rows(role_menu_block):
        args = _split_sql_args(raw)
        if len(args) < 3:
            continue
        role_id = canon_id(int(args[1]))
        menu_id = canon_id(int(args[2]))
        bindings.setdefault(role_id, set()).add(menu_id)
    return menus, roles, bindings


def seed_perms(menus: dict[int, SeedMenu]) -> set[str]:
    return {row.perms for row in menus.values() if row.perms}


@dataclass(frozen=True)
class RouteGate:
    method: str
    path: str
    jwt: bool
    rbac: bool
    perm: str | None
    file: str


def _literal_str(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _has_name(node: ast.AST, name: str) -> bool:
    if isinstance(node, ast.Name) and node.id == name:
        return True
    if isinstance(node, ast.Call):
        return _has_name(node.func, name) or any(_has_name(arg, name) for arg in node.args)
    return False


def _request_permission(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    if not (isinstance(node.func, ast.Name) and node.func.id == 'Depends'):
        return None
    if not node.args:
        return None
    inner = node.args[0]
    if (
        isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Name)
        and inner.func.id == 'RequestPermission'
        and inner.args
    ):
        return _literal_str(inner.args[0])
    return None


def _v1_router_aliases(tree: ast.AST) -> dict[str, tuple[str, str]]:
    aliases: dict[str, tuple[str, str]] = {}
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not node.module.startswith('backend.plugin.rider_salary.api.v1.'):
            continue
        module = node.module.rsplit('.', 1)[-1]
        for alias in node.names:
            aliases[alias.asname or alias.name] = (module, alias.name)
    return aliases


def _include_prefix(node: ast.Call, aliases: dict[str, tuple[str, str]]) -> tuple[str, str] | None:
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == 'include_router' and node.args):
        return None
    router_name = node.args[0].id if isinstance(node.args[0], ast.Name) else None
    if not router_name or router_name not in aliases:
        return None
    prefix = ''
    for kw in node.keywords:
        if kw.arg == 'prefix':
            prefix = _literal_str(kw.value) or ''
    return router_name, prefix


def _router_prefixes() -> dict[str, str]:
    """从 api/router.py 的 include_router 还原「模块文件 + 路由器变量 → 前缀」。"""
    tree = ast.parse(ROUTER_FILE.read_text(encoding='utf-8'))
    aliases = _v1_router_aliases(tree)
    prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        found = _include_prefix(node, aliases)
        if found is None:
            continue
        router_name, prefix = found
        module, exported = aliases[router_name]
        prefixes[f'{module}:{exported}'] = prefix
        prefixes[f'{module}:{_export_to_var(exported)}'] = prefix
    return prefixes


def _export_to_var(exported: str) -> str:
    if exported == 'batch_router':
        return 'batch_router'
    if exported == 'version_router':
        return 'version_router'
    return 'router'


def _join_route(prefix: str, rel: str | None) -> str:
    part = rel or ''
    full = f'{prefix}{part}' if part.startswith('/') or not part else f'{prefix}/{part}'
    if full != '/' and full.endswith('/'):
        full = full.rstrip('/')
    return full or '/'


def _deps_gate(items: list[ast.expr]) -> tuple[bool, bool, str | None]:
    jwt = False
    rbac = False
    perm: str | None = None
    for item in items:
        jwt = jwt or _has_name(item, 'DependsJwtAuth')
        rbac = rbac or _has_name(item, 'DependsRBAC')
        found = _request_permission(item)
        if found:
            perm = found
    return jwt, rbac, perm


def _route_from_decorator(deco: ast.Call, prefixes: dict[str, str], stem: str, filename: str) -> RouteGate | None:
    if not isinstance(deco.func, ast.Attribute):
        return None
    method = deco.func.attr.upper()
    if method not in {'GET', 'POST', 'PUT', 'DELETE', 'PATCH'}:
        return None
    router_var = deco.func.value.id if isinstance(deco.func.value, ast.Name) else 'router'
    rel = _literal_str(deco.args[0]) if deco.args else ''
    jwt = False
    rbac = False
    perm: str | None = None
    for kw in deco.keywords:
        if kw.arg != 'dependencies' or not isinstance(kw.value, ast.List):
            continue
        jwt, rbac, perm = _deps_gate(kw.value.elts)
    return RouteGate(
        method=method,
        path=_join_route(prefixes.get(f'{stem}:{router_var}', ''), rel),
        jwt=jwt,
        rbac=rbac,
        perm=perm,
        file=filename,
    )


def scan_api_gates() -> list[RouteGate]:
    """静态扫描插件 v1 路由的 JWT / RBAC / RequestPermission。"""
    prefixes = _router_prefixes()
    routes: list[RouteGate] = []
    for path in sorted(API_V1.glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            for deco in node.decorator_list:
                if not isinstance(deco, ast.Call):
                    continue
                gate = _route_from_decorator(deco, prefixes, path.stem, path.name)
                if gate is not None:
                    routes.append(gate)
    return routes


def jwt_only_paths(routes: list[RouteGate]) -> set[str]:
    return {row.path for row in routes if row.jwt and not row.rbac and row.perm is None}


def read_hung_on_write(routes: list[RouteGate]) -> dict[tuple[str, str], str]:
    found: dict[tuple[str, str], str] = {}
    for row in routes:
        if row.method != 'GET' or not row.perm:
            continue
        action = row.perm.rsplit(':', 1)[-1]
        if action in WRITE_LIKE_ACTIONS:
            found[row.method, row.path] = row.perm
    return found

import ast
import os
import re
import subprocess
import uuid

from pathlib import Path
from typing import NamedTuple

import anyio
import pytest
import sqlparse

from backend.utils.sql_parser import parse_sql_script

SQL_ROOT = Path(__file__).resolve().parents[1] / 'sql'
# 初始化/销毁脚本只在 postgresql、mysql 两个目录。sql/patch 是增量补丁，单独约束。
SQL_FILES = sorted(path for directory in ('postgresql', 'mysql') for path in (SQL_ROOT / directory).glob('*.sql'))
PATCH_FILES = sorted((SQL_ROOT / 'patch').glob('*.sql'))


def test_plugin_sql_files_exist() -> None:
    assert len(SQL_FILES) == 8


def test_plugin_sql_files_parseable() -> None:
    async def _run() -> None:
        for path in SQL_FILES:
            is_destroy = 'destroy' in path.name
            statements = await parse_sql_script(str(path), is_destroy=is_destroy)
            assert statements, path
            first = statements[0].strip().lower()
            assert not first.startswith('--'), path

    anyio.run(_run)


def _strip_leading_line_comments(statement: str) -> str:
    lines = statement.splitlines()
    index = 0
    while index < len(lines) and (not lines[index].strip() or lines[index].strip().startswith('--')):
        index += 1
    return '\n'.join(lines[index:]).strip()


def _is_idempotent(statement: str) -> bool:
    """写语句必须能重复执行：插入带判重，DDL 带 if [not] exists。"""
    body = ' '.join(_strip_leading_line_comments(statement).lower().split())
    if not body:
        return True
    head = body.split(' ', 1)[0]
    if head == 'insert':
        return 'where not exists' in body or 'on conflict' in body
    if head == 'create':
        return 'if not exists' in body
    if head in {'drop', 'alter'}:
        return 'if exists' in body or 'if not exists' in body
    return head in {'select', 'set', 'do'}


def test_patch_sql_has_no_leading_comment() -> None:
    assert PATCH_FILES, 'sql/patch 下应至少有一份增量脚本'
    for path in PATCH_FILES:
        text = path.read_text(encoding='utf-8')
        assert not text.lstrip().startswith('--'), path


def test_patch_sql_is_idempotent() -> None:
    assert PATCH_FILES, 'sql/patch 下应至少有一份增量脚本'
    for path in PATCH_FILES:
        statements = [stmt.strip() for stmt in sqlparse.split(path.read_text(encoding='utf-8')) if stmt.strip()]
        assert statements, path
        for statement in statements:
            assert _is_idempotent(statement), (path, statement)


# 自增种子段和雪花偏移段。补丁里出现这些字面量，说明仍按固定主键判重。
_FIXED_PK_ID = re.compile(r'\b(?:91\d{3}|92\d{3}|93\d{3}|94\d{3}|2060\d+)\b')
_ROLE_NAMES = ('薪资管理员', '站点负责人', '站点副负责人')
_PATCH_001 = SQL_ROOT / 'patch' / '001_rider_detail_menu.sql'
_PATCH_002 = SQL_ROOT / 'patch' / '002_period_delete_perm.sql'


def _patch_text(path: Path) -> str:
    text = path.read_text(encoding='utf-8')
    assert not text.lstrip().startswith('--'), path
    assert not _FIXED_PK_ID.search(text), (path, _FIXED_PK_ID.findall(text))
    assert 'pg_get_serial_sequence' in text, path
    assert 'max(id)' in text, path
    for role_name in _ROLE_NAMES:
        assert f"name = '{role_name}'" in text, (path, role_name)
    return text


def test_rider_detail_patch_dedups_by_menu_name() -> None:
    text = _patch_text(_PATCH_001)
    assert "where not exists (select 1 from sys_menu where name = 'RiderSalaryRiderDetail')" in text
    assert "where name = 'RiderSalary'" in text
    assert "(select id from sys_menu where name = 'RiderSalaryRiderDetail')" in text
    assert 'id = 91015' not in text
    assert 'where id =' not in text.lower()


def test_period_delete_patch_dedups_by_perms() -> None:
    text = _patch_text(_PATCH_002)
    assert "where not exists (select 1 from sys_menu where perms = 'rs:period:delete')" in text
    assert "where name = 'RiderSalaryPeriod'" in text
    assert "(select id from sys_menu where perms = 'rs:period:delete')" in text
    assert 'rs:period:delete' in text
    assert 'RiderSalaryPeriodDelete' in text


def _psql(database: str, sql: str, *, file: Path | None = None) -> str:
    env = os.environ.copy()
    env['PGPASSWORD'] = 'postgres'
    env['PGHOST'] = '127.0.0.1'
    env['PGUSER'] = 'root'
    command = ['psql', '-d', database, '-v', 'ON_ERROR_STOP=1', '-tA']
    if file is not None:
        command.extend(['-f', str(file)])
    completed = subprocess.run(
        command, input=None if file else sql, text=True, capture_output=True, env=env, check=False
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    return completed.stdout


def _postgres_ready() -> bool:
    try:
        _psql('postgres', 'select 1')
    except (AssertionError, FileNotFoundError):
        return False
    return True


def _drop_database(name: str) -> None:
    _psql(
        'postgres',
        f"""
        select pg_terminate_backend(pid)
        from pg_stat_activity
        where datname = '{name}' and pid <> pg_backend_pid();
        drop database if exists {name};
        """,
    )


def _create_menu_schema(database: str, *, snowflake: bool) -> None:
    menu_id = 'id bigint primary key' if snowflake else 'id bigserial primary key'
    _psql(
        database,
        f"""
        create table sys_menu (
            {menu_id},
            title varchar(64) not null,
            name varchar(64) not null,
            path varchar(200),
            sort integer not null,
            icon varchar(128),
            type integer not null,
            component varchar(256),
            perms varchar(128),
            status integer not null,
            display integer not null,
            cache integer not null,
            link text,
            remark text,
            parent_id bigint,
            created_time timestamptz not null,
            updated_time timestamptz
        );
        create table sys_role (
            id bigint primary key,
            name varchar(32) not null,
            deleted bigint not null default 0
        );
        create table sys_role_menu (
            id bigserial primary key,
            role_id bigint not null,
            menu_id bigint not null
        );
        """,
    )


def _seed_old_library(database: str, *, snowflake: bool) -> None:
    """模拟补丁写入前的库：父菜单和角色在，目标菜单不在，且 91015 已被别的菜单占用。"""
    if snowflake:
        root_id, period_id = 2060000000000091000, 2060000000000091010
        role_ids = (2060000000000092001, 2060000000000092002, 2060000000000092003)
    else:
        root_id, period_id = 91000, 91010
        role_ids = (70001, 70002, 70003)
    menu_cols = (
        'id, title, name, path, sort, icon, type, component, perms, status, display, cache, '
        'link, remark, parent_id, created_time, updated_time'
    )
    _psql(
        database,
        f"""
        insert into sys_menu ({menu_cols})
        values
        (
            {root_id}, '骑手薪资', 'RiderSalary', '/rider-salary', 20, null, 0, null, null,
            1, 1, 1, '', null, null, now(), null
        ),
        (
            {period_id}, '结算周期', 'RiderSalaryPeriod', '/rider-salary/period', 10, null, 1, null, null,
            1, 1, 1, '', null, {root_id}, now(), null
        ),
        (
            91015, '占用', 'OccupiedMenu', '/occupied', 0, null, 1, null, 'other:occupied',
            1, 1, 1, '', null, null, now(), null
        );
        insert into sys_role (id, name) values
        ({role_ids[0]}, '薪资管理员'),
        ({role_ids[1]}, '站点负责人'),
        ({role_ids[2]}, '站点副负责人');
        insert into sys_role_menu (id, role_id, menu_id)
        values
        (1, {role_ids[0]}, {root_id}),
        (2, {role_ids[0]}, {period_id}),
        (3, {role_ids[0]}, 91015);
        select setval(pg_get_serial_sequence('sys_role_menu', 'id'), 1, false);
        """,
    )
    if not snowflake:
        _psql(database, "select setval(pg_get_serial_sequence('sys_menu', 'id'), 1, false);")


def _apply_patches(database: str) -> None:
    _psql(database, '', file=_PATCH_001)
    _psql(database, '', file=_PATCH_002)


def _menu_snapshot(database: str) -> str:
    return _psql(
        database,
        """
        select m.name, m.perms, m.id, m.parent_id,
               (select p.name from sys_menu p where p.id = m.parent_id)
        from sys_menu m
        where m.name in ('RiderSalaryRiderDetail', 'RiderSalaryPeriodDelete', 'OccupiedMenu')
        order by m.name;
        """,
    )


def _binding_snapshot(database: str) -> str:
    return _psql(
        database,
        """
        select r.name, m.name, coalesce(m.perms, ''), (m.id <> 91015)::int
        from sys_role_menu rm
        join sys_role r on r.id = rm.role_id
        join sys_menu m on m.id = rm.menu_id
        where m.name in ('RiderSalaryRiderDetail', 'RiderSalaryPeriodDelete')
        order by m.name, r.name;
        """,
    )


def test_patches_apply_twice_on_autoincrement_and_snowflake() -> None:
    if not _postgres_ready():
        pytest.skip('本机 PostgreSQL 不可达，跳过补丁执行')
    suffix = f'{os.getpid()}_{uuid.uuid4().hex[:8]}'
    databases = {
        f'rs_p404_auto_{suffix}': False,
        f'rs_p404_snow_{suffix}': True,
    }
    for name in databases:
        _drop_database(name)
    try:
        for name, snowflake in databases.items():
            _psql('postgres', f'create database {name}')
            _create_menu_schema(name, snowflake=snowflake)
            _seed_old_library(name, snowflake=snowflake)
            _apply_patches(name)
            first_menus = _menu_snapshot(name)
            first_bindings = _binding_snapshot(name)
            assert first_menus.count('RiderSalaryRiderDetail') == 1, first_menus
            assert first_menus.count('RiderSalaryPeriodDelete') == 1, first_menus
            assert 'OccupiedMenu' in first_menus
            assert 'rs:period:delete' in first_menus
            assert first_bindings.count('|1') == 6, first_bindings
            for role_name in _ROLE_NAMES:
                assert first_bindings.count(role_name) == 2, first_bindings
            detail_parent = _psql(
                name,
                """
                select p.name
                from sys_menu m
                join sys_menu p on p.id = m.parent_id
                where m.name = 'RiderSalaryRiderDetail'
                """,
            ).strip()
            delete_parent = _psql(
                name,
                """
                select p.name
                from sys_menu m
                join sys_menu p on p.id = m.parent_id
                where m.perms = 'rs:period:delete'
                """,
            ).strip()
            assert detail_parent == 'RiderSalary'
            assert delete_parent == 'RiderSalaryPeriod'
            _apply_patches(name)
            assert _menu_snapshot(name) == first_menus
            assert _binding_snapshot(name) == first_bindings
    finally:
        for name in databases:
            _drop_database(name)


# --- P1-06：四份 init 的权限、菜单、组件、负责人角色 ---
#
# 待修清单。只登记已经核对过、本次不改 SQL / 接口的差异。
# 测试会放行清单里的项；清单外的差异仍然失败。修掉后把条目删掉。
# 清单里已经不存在的差异也会失败，避免清单过期。
#
# 核对结果（postgresql/init.sql 为基准）：四份 init 的 rs:* 权限码、菜单行、
# 页面 component、站点负责人 / 站点副负责人绑定一致；api/v1 的 RequestPermission
# 都落在 init 权限集合内。因此下面四项都是空的。
# permission_gaps：相对路径（如 mysql/init.sql）→ 与基准对称差集里的 rs:* 权限码
PENDING_PERMISSION_GAPS: dict[str, frozenset[str]] = {}
# menu_name_gaps：相对路径 → 允许与基准菜单行不一致的菜单 name
PENDING_MENU_NAME_GAPS: dict[str, frozenset[str]] = {}
# 接口用了、但基准 init 没有菜单行的权限码
PENDING_API_WITHOUT_MENU: frozenset[str] = frozenset()
# init 写了、管理端没有对应 .vue 的 component
PENDING_MISSING_VUE: frozenset[str] = frozenset()
# Q-03 推荐方案 B：负责人不该有、但 SQL 里仍然绑定了的权限码
PENDING_OWNER_FORBIDDEN: frozenset[str] = frozenset()

_INIT_SQL_NAMES = (
    'mysql/init.sql',
    'mysql/init_snowflake.sql',
    'postgresql/init.sql',
    'postgresql/init_snowflake.sql',
)
_BASELINE_INIT = 'postgresql/init.sql'
_COMPONENT_PREFIX = '/plugins/rider-salary/'
_OWNER_ROLES = ('站点负责人', '站点副负责人')
_FORBIDDEN_OWNER_PERMS = frozenset({'rs:period:reverse', 'rs:rider:account'})
_PERM_CODE = re.compile(r'^rs:[a-z0-9_]+:[a-z0-9_-]+$')
_QUOTED = r"'(?:\\'|[^'])*'"
_MENU_ROW = re.compile(
    rf'\('
    rf'(\d+),\s*'
    rf"'((?:\\'|[^'])*)',\s*"
    rf"'((?:\\'|[^'])*)',\s*"
    rf'(?:null|{_QUOTED}),\s*'
    rf'\d+,\s*'
    rf'(?:null|{_QUOTED}),\s*'
    rf'(\d+),\s*'
    rf'(null|{_QUOTED}),\s*'
    rf'(null|{_QUOTED})'
)
_ROLE_ROW = re.compile(r"\((\d+),\s*'([^']*)'")
_ROLE_MENU_ROW = re.compile(r'\((\d+),\s*(\d+),\s*(\d+)\)')


class _MenuRow(NamedTuple):
    menu_id: str
    name: str
    menu_type: str
    component: str | None
    perms: str | None


def _init_sql_files() -> list[Path]:
    files = sorted(path for path in SQL_FILES if path.name.startswith('init'))
    found = [path.relative_to(SQL_ROOT).as_posix() for path in files]
    assert found == list(_INIT_SQL_NAMES), found
    return files


def _sql_rel(path: Path) -> str:
    return f'{path.parent.name}/{path.name}'


def _baseline_init(files: list[Path]) -> Path:
    for path in files:
        if _sql_rel(path) == _BASELINE_INIT:
            return path
    raise AssertionError(f'缺少 {_BASELINE_INIT}')


def _insert_blocks(text: str, table: str) -> str:
    chunks: list[str] = []
    for part in re.split(r'(?=insert into\s+)', text):
        head = part.lstrip()
        if re.match(rf'insert into\s+{re.escape(table)}(?:\s|\()', head):
            chunks.append(head)
    return '\n'.join(chunks)


def _tuple_lines(body: str) -> list[str]:
    return [line.strip() for line in body.splitlines() if line.strip().startswith('(')]


def _sql_literal(raw: str) -> str | None:
    if raw == 'null':
        return None
    assert raw.startswith("'") and raw.endswith("'"), raw
    return raw[1:-1].replace("\\'", "'")


def _parse_menus(text: str) -> list[_MenuRow]:
    rows: list[_MenuRow] = []
    seen: set[str] = set()
    for line in _tuple_lines(_insert_blocks(text, 'sys_menu')):
        match = _MENU_ROW.match(line)
        assert match, f'无法解析菜单行: {line[:160]}'
        menu_id, _title, name, menu_type, component, perms = match.groups()
        assert name not in seen, name
        seen.add(name)
        perm = _sql_literal(perms)
        if perm is not None:
            assert _PERM_CODE.fullmatch(perm), perm
        rows.append(_MenuRow(menu_id, name, menu_type, _sql_literal(component), perm))
    assert rows, 'init 里没有菜单行'
    return rows


def _permission_codes(menus: list[_MenuRow]) -> set[str]:
    return {menu.perms for menu in menus if menu.perms is not None}


def _menu_signature(menu: _MenuRow) -> tuple[str, str, str, str]:
    return (menu.name, menu.menu_type, menu.component or '', menu.perms or '')


def _parse_roles(text: str) -> dict[str, str]:
    roles: dict[str, str] = {}
    for line in _tuple_lines(_insert_blocks(text, 'sys_role')):
        match = _ROLE_ROW.match(line)
        assert match, f'无法解析角色行: {line[:160]}'
        role_id, name = match.groups()
        assert role_id not in roles, role_id
        roles[role_id] = name
    assert roles, 'init 里没有角色行'
    return roles


def _parse_role_menus(text: str) -> list[tuple[str, str]]:
    bindings: list[tuple[str, str]] = []
    for line in _tuple_lines(_insert_blocks(text, 'sys_role_menu')):
        match = _ROLE_MENU_ROW.match(line)
        assert match, f'无法解析角色菜单行: {line[:160]}'
        _binding_id, role_id, menu_id = match.groups()
        bindings.append((role_id, menu_id))
    assert bindings, 'init 里没有角色菜单行'
    return bindings


def _role_permissions(text: str, role_name: str) -> set[str]:
    menus = {menu.menu_id: menu for menu in _parse_menus(text)}
    role_ids = [role_id for role_id, name in _parse_roles(text).items() if name == role_name]
    assert len(role_ids) == 1, (role_name, role_ids)
    perms: set[str] = set()
    bound = False
    for role_id, menu_id in _parse_role_menus(text):
        if role_id != role_ids[0]:
            continue
        bound = True
        menu = menus.get(menu_id)
        assert menu is not None, (role_name, menu_id)
        if menu.perms is not None:
            perms.add(menu.perms)
    assert bound, role_name
    return perms


def _admin_vue_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = (
            parent / 'fastapi-best-architecture-ui' / 'apps' / 'web-antdv-next' / 'src' / 'plugins' / 'rider-salary'
        )
        if candidate.is_dir():
            return candidate
    raise AssertionError('找不到管理端插件目录')


def _component_vue(component: str, vue_root: Path) -> Path:
    assert component.startswith(_COMPONENT_PREFIX), component
    relative = component[len(_COMPONENT_PREFIX) :]
    assert relative and '..' not in relative.split('/'), component
    return vue_root / f'{relative}.vue'


def _request_permission_codes(api_dir: Path) -> set[str]:
    files = sorted(api_dir.glob('*.py'))
    assert files, api_dir
    codes: set[str] = set()
    for path in files:
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            else:
                continue
            if name != 'RequestPermission':
                continue
            arg = node.args[0] if node.args else None
            assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), (
                f'{path}:{node.lineno} 的 RequestPermission 必须是字符串字面量'
            )
            codes.add(arg.value)
    assert codes, api_dir
    return codes


def assert_init_permission_sets_match(files: list[Path] | None = None) -> None:
    """四份 init 的 rs:* 权限码集合相同。待修清单里的差集除外。"""
    chosen = list(files or _init_sql_files())
    base_codes = _permission_codes(_parse_menus(_baseline_init(chosen).read_text(encoding='utf-8')))
    assert base_codes, '基准 init 没有 rs:* 权限码'
    for path in chosen:
        rel = _sql_rel(path)
        codes = _permission_codes(_parse_menus(path.read_text(encoding='utf-8')))
        gap = codes ^ base_codes
        pending = PENDING_PERMISSION_GAPS.get(rel, frozenset())
        unexpected = gap - pending
        assert not unexpected, (rel, sorted(unexpected))
        stale = pending - gap
        assert not stale, (rel, sorted(stale))


def assert_init_menu_rows_match(files: list[Path] | None = None) -> None:
    """四份 init 的菜单 name、类型、component、权限码一致。删掉任一行都会失败。"""
    chosen = list(files or _init_sql_files())
    base_sig = {
        menu.name: _menu_signature(menu) for menu in _parse_menus(_baseline_init(chosen).read_text(encoding='utf-8'))
    }
    for path in chosen:
        rel = _sql_rel(path)
        file_sig = {menu.name: _menu_signature(menu) for menu in _parse_menus(path.read_text(encoding='utf-8'))}
        pending = PENDING_MENU_NAME_GAPS.get(rel, frozenset())
        only_base = set(base_sig) - set(file_sig) - pending
        only_file = set(file_sig) - set(base_sig) - pending
        changed = {name for name in (set(base_sig) & set(file_sig)) - pending if base_sig[name] != file_sig[name]}
        assert not only_base and not only_file and not changed, (
            rel,
            sorted(only_base),
            sorted(only_file),
            sorted(changed),
        )
        stale = {name for name in pending if base_sig.get(name) == file_sig.get(name)}
        assert not stale, (rel, sorted(stale))


def assert_request_permissions_covered(
    api_dir: Path | None = None,
    files: list[Path] | None = None,
) -> None:
    """api/v1 的 RequestPermission 必须是基准 init 权限集合的子集。"""
    chosen = list(files or _init_sql_files())
    init_codes = _permission_codes(_parse_menus(_baseline_init(chosen).read_text(encoding='utf-8')))
    api_codes = _request_permission_codes(api_dir or (Path(__file__).resolve().parents[1] / 'api' / 'v1'))
    extra = api_codes - init_codes - PENDING_API_WITHOUT_MENU
    assert not extra, sorted(extra)
    stale = PENDING_API_WITHOUT_MENU - (api_codes - init_codes)
    assert not stale, sorted(stale)


def assert_menu_components_exist(files: list[Path] | None = None, vue_root: Path | None = None) -> None:
    """菜单 component 去掉前缀后，管理端必须有同名 .vue。"""
    root = vue_root or _admin_vue_root()
    missing: set[str] = set()
    seen: set[str] = set()
    for path in files or _init_sql_files():
        for menu in _parse_menus(path.read_text(encoding='utf-8')):
            if menu.component is None:
                continue
            seen.add(menu.component)
            if not _component_vue(menu.component, root).is_file():
                missing.add(menu.component)
    assert seen, 'init 应包含页面 component'
    unexpected = missing - PENDING_MISSING_VUE
    assert not unexpected, sorted(unexpected)
    stale = PENDING_MISSING_VUE - missing
    assert not stale, sorted(stale)


def assert_site_owner_lacks_forbidden_perms(files: list[Path] | None = None) -> None:
    """Q-03 推荐方案 B：站点负责人与副负责人不能反冲补发，也不能开通骑手账号。"""
    chosen = list(files or _init_sql_files())
    observed: set[str] = set()
    for path in chosen:
        text = path.read_text(encoding='utf-8')
        for role_name in _OWNER_ROLES:
            actual = _role_permissions(text, role_name) & _FORBIDDEN_OWNER_PERMS
            observed |= actual
            unexpected = actual - PENDING_OWNER_FORBIDDEN
            assert not unexpected, (_sql_rel(path), role_name, sorted(unexpected))
    stale = PENDING_OWNER_FORBIDDEN - observed
    assert not stale, sorted(stale)


def test_init_rs_permission_sets_match() -> None:
    assert_init_permission_sets_match()


def test_init_menu_rows_match() -> None:
    assert_init_menu_rows_match()


def test_request_permissions_are_init_subset() -> None:
    assert_request_permissions_covered()


def test_menu_components_have_vue_files() -> None:
    assert_menu_components_exist()


def test_site_owner_cannot_reverse_or_open_account() -> None:
    assert_site_owner_lacks_forbidden_perms()

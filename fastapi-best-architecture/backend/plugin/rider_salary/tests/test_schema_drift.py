"""对比插件 ORM metadata 与当前 PostgreSQL，模型有列而库里没有时失败。

只读连接 ``settings.DATABASE_SCHEMA`` 指向的库（本机是 ``fba``；``127.0.0.1:5432``，用户 ``root``）。不建库、不改表。
``create_all`` 不会给已有表补列。CI 里如果先 ``create_all``，连库对比看不出漏写的 patch，
所以另有一份列清单：模型比清单多出来的列必须出现在 ``sql/patch/`` 里。
"""

import json

from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from pathlib import Path

import psycopg
import pytest

import backend.plugin.rider_salary.model as rider_salary_model

from backend.common.model import MappedBase
from backend.core.conf import settings

_DB_HOST = '127.0.0.1'
_DB_PORT = 5432
_DB_USER = 'root'
_DB_PASSWORD = 'postgres'
_PUBLIC_SCHEMA = 'public'
_MODEL_MODULE_PREFIX = 'backend.plugin.rider_salary.model.'


def plugin_orm_columns() -> dict[str, set[str]]:
    """收集骑手薪资插件模型的表名和列名。"""
    assert rider_salary_model.__name__.startswith('backend.plugin.rider_salary.model')
    columns: dict[str, set[str]] = {}
    for mapper in MappedBase.registry.mappers:
        cls = mapper.class_
        if not cls.__module__.startswith(_MODEL_MODULE_PREFIX):
            continue
        table = mapper.local_table
        if table.schema not in (None, _PUBLIC_SCHEMA):
            msg = f'表 {table.name} 的 schema 是 {table.schema}，漂移检查只覆盖 public'
            raise AssertionError(msg)
        columns[table.name] = {column.name for column in table.columns}
    return columns


def find_missing_columns(
    orm_columns: Mapping[str, AbstractSet[str]],
    db_columns: Mapping[str, AbstractSet[str]],
) -> list[tuple[str, str]]:
    """返回模型有、库里没有的 ``(表名, 列名)``，按表名、列名排序。"""
    missing: list[tuple[str, str]] = []
    for table in sorted(orm_columns):
        present = db_columns.get(table, set())
        missing.extend((table, column) for column in sorted(orm_columns[table] - present))
    return missing


def format_missing_columns(
    missing: Sequence[tuple[str, str]],
    *,
    absent_tables: AbstractSet[str] = frozenset(),
) -> str:
    """把缺列写成带表名和列名的说明。整表不存在时单独标出。"""
    lines = ['模型有列但数据库没有：']
    for table, column in missing:
        if table in absent_tables:
            lines.append(f'表 {table} 不存在，缺少列 {column}')
        else:
            lines.append(f'表 {table} 缺少列 {column}')
    return '\n'.join(lines)


def fetch_public_columns(
    conn: psycopg.Connection,
    tables: AbstractSet[str],
) -> tuple[dict[str, set[str]], set[str]]:
    """从 ``information_schema`` 读取 public 下指定表的列，并返回库里不存在的表。"""
    table_names = list(tables)
    column_rows = conn.execute(
        """
        select table_name, column_name
        from information_schema.columns
        where table_schema = %s
          and table_name = any(%s)
        """,
        (_PUBLIC_SCHEMA, table_names),
    ).fetchall()
    found: dict[str, set[str]] = {}
    for table_name, column_name in column_rows:
        found.setdefault(table_name, set()).add(column_name)
    existing_rows = conn.execute(
        """
        select table_name
        from information_schema.tables
        where table_schema = %s
          and table_type = 'BASE TABLE'
          and table_name = any(%s)
        """,
        (_PUBLIC_SCHEMA, table_names),
    ).fetchall()
    existing = {row[0] for row in existing_rows}
    return found, set(tables) - existing


def test_missing_column_message_names_table_and_column() -> None:
    """模型多一列时，失败信息同时包含表名和列名。"""
    missing = find_missing_columns(
        {'rs_demo': {'id', 'extra_col'}},
        {'rs_demo': {'id'}},
    )
    message = format_missing_columns(missing)
    assert missing == [('rs_demo', 'extra_col')]
    with pytest.raises(AssertionError, match='表 rs_demo 缺少列 extra_col'):
        assert not missing, message


def test_missing_table_message_names_each_column() -> None:
    """整张表都不在库里时，每一列都带上表名。"""
    missing = find_missing_columns(
        {'rs_demo': {'id', 'name'}},
        {},
    )
    message = format_missing_columns(missing, absent_tables={'rs_demo'})
    assert '表 rs_demo 不存在，缺少列 id' in message
    assert '表 rs_demo 不存在，缺少列 name' in message


def test_extra_database_column_is_ignored() -> None:
    """库里多出来的列不判失败。create_all 漏掉的是模型有而库里没有的列。"""
    missing = find_missing_columns(
        {'rs_demo': {'id'}},
        {'rs_demo': {'id', 'legacy_col'}},
    )
    assert missing == []


@pytest.mark.integration
def test_fba_has_every_plugin_model_column() -> None:
    """配置库 public 表必须含有插件模型的每一列。本机配置库是 fba。"""
    db_name = settings.DATABASE_SCHEMA
    orm_columns = plugin_orm_columns()
    assert orm_columns, '没有收集到骑手薪资插件的模型表'
    try:
        conn = psycopg.connect(
            host=_DB_HOST,
            port=_DB_PORT,
            user=_DB_USER,
            password=_DB_PASSWORD,
            dbname=db_name,
            connect_timeout=5,
            options='-c default_transaction_read_only=on',
        )
    except psycopg.Error as exc:
        pytest.fail(f'无法只读连接数据库 {db_name}：{exc}')
    with conn:
        current = conn.execute('select current_database()').fetchone()
        readonly = conn.execute('show default_transaction_read_only').fetchone()
        db_columns, absent_tables = fetch_public_columns(conn, set(orm_columns))
        conn.rollback()
    assert current is not None
    assert current[0] == db_name
    assert readonly is not None
    assert readonly[0] == 'on'
    missing = find_missing_columns(orm_columns, db_columns)
    assert not missing, format_missing_columns(missing, absent_tables=absent_tables)


_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
_BASELINE_PATH = Path(__file__).resolve().parent / 'schema_column_baseline.json'


def patch_sql_text() -> str:
    """全部增量脚本拼在一起，用来确认新列写进了 patch。"""
    folder = _PLUGIN_ROOT / 'sql' / 'patch'
    return '\n'.join(path.read_text(encoding='utf-8') for path in sorted(folder.glob('*.sql')))


def columns_added_without_patch(
    orm_columns: Mapping[str, AbstractSet[str]],
    baseline: Mapping[str, Sequence[str]],
    patch_text: str,
) -> list[tuple[str, str]]:
    """模型比已登记清单多出来、且 patch 文本里没有的列。"""
    missing: list[tuple[str, str]] = []
    for table in sorted(orm_columns):
        known = set(baseline.get(table, ()))
        missing.extend((table, column) for column in sorted(orm_columns[table] - known) if column not in patch_text)
    return missing


def test_new_model_column_without_patch_is_reported() -> None:
    """模型加一列、不写 patch 时，检查结果点名表和列。"""
    missing = columns_added_without_patch(
        {'rs_order': {'id', 'extra_col'}},
        {'rs_order': ['id']},
        'alter table rs_order add column other_col bigint',
    )
    assert missing == [('rs_order', 'extra_col')]


def test_current_model_columns_are_baselined_or_in_a_patch() -> None:
    """当前模型列要么已在清单里，要么写进了 sql/patch。漏写 patch 时本用例失败。"""
    baseline = json.loads(_BASELINE_PATH.read_text(encoding='utf-8'))
    missing = columns_added_without_patch(plugin_orm_columns(), baseline, patch_sql_text())
    assert not missing, format_missing_columns(missing)

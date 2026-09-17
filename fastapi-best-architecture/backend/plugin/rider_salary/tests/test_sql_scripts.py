from pathlib import Path

import anyio

from backend.utils.sql_parser import parse_sql_script

SQL_ROOT = Path(__file__).resolve().parents[1] / 'sql'
<<<<<<< HEAD
# init/destroy only；patch 由手工/运维执行，不走 FBA 插件 SQL 解析器
SQL_FILES = sorted(p for p in SQL_ROOT.glob('*/*.sql') if p.parent.name != 'patch')
=======
SQL_FILES = sorted(path for dialect in ('mysql', 'postgresql') for path in (SQL_ROOT / dialect).glob('*.sql'))
>>>>>>> origin/cursor/advance-site-quota-e2c8


def test_plugin_sql_files_exist() -> None:
    assert len(SQL_FILES) == 8
    assert not any(p.parent.name == 'patch' for p in SQL_FILES)


def test_plugin_sql_files_parseable() -> None:
    async def _run() -> None:
        for path in SQL_FILES:
            is_destroy = 'destroy' in path.name
            statements = await parse_sql_script(str(path), is_destroy=is_destroy)
            assert statements, path
            first = statements[0].strip().lower()
            assert not first.startswith('--'), path

    anyio.run(_run)

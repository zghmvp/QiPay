"""插件测试入口。

rootdir 由插件目录的 pytest.ini 固定，因此不会加载框架 ``backend/conftest.py``。
``tests/integration/`` 只在 Redis 与 PostgreSQL 探测通过后才导入应用，避免导入时 ``sys.exit(0)`` 假绿。
"""

import sys

from pathlib import Path

import pytest

_FRAMEWORK_IMPORT_GUARD = (
    '插件测试加载了框架入口（backend.main）。Redis 不可达时该导入会 sys.exit(0)，'
    'pytest 将以 0 个用例成功退出。请保留插件目录的 pytest.ini，使测试根目录停在插件内。'
)


def pytest_configure(config: pytest.Config) -> None:
    """发现框架入口被导入时失败退出，避免 Redis 不可达造成假绿。

    :param config: pytest 配置对象
    :return:
    """
    if config.rootpath.name != 'rider_salary':
        pytest.exit(
            '插件测试根目录不在 rider_salary，框架 conftest 可能被加载。'
            '请运行 backend/plugin/rider_salary/tests，以使用插件目录的 pytest.ini。',
            returncode=1,
        )
    if 'backend.main' in sys.modules or 'backend.conftest' in sys.modules:
        pytest.exit(_FRAMEWORK_IMPORT_GUARD, returncode=1)


def pytest_collection_finish(session: pytest.Session) -> None:
    """打印收集到的用例数；一个都没有时拒绝成功退出。

    :param session: 当前测试会话
    :return:
    """
    count = len(session.items)
    reporter = session.config.pluginmanager.get_plugin('terminalreporter')
    if count == 0:
        message = '未收集到任何测试用例，拒绝以成功退出'
        sys.stderr.write(f'{message}\n')
        if reporter is not None:
            reporter.write_line(message)
        pytest.exit(message, returncode=1)
    if reporter is not None:
        reporter.write_line(f'已收集 {count} 个用例')


def pytest_runtest_setup(item: pytest.Item) -> None:
    """离开集成目录前关掉基座，避免事件循环占用全局 Redis 客户端。

    :param item: 即将执行的用例
    :return:
    """
    runtime_mod = sys.modules.get('runtime')
    if runtime_mod is None:
        return
    current = getattr(runtime_mod, 'ACTIVE', None)
    if current is None:
        return
    if 'integration' in Path(str(item.fspath)).parts:
        return
    current.close()

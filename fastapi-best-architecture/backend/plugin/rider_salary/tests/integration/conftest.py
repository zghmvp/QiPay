"""集成测试夹具。只在本目录生效，不改变纯函数测试的导入方式。"""

import sys

from pathlib import Path

import pytest

_INTEGRATION_DIR = Path(__file__).resolve().parent
# 追加到末尾，避免盖住 tests/ 下同名模块。用例文件名仍必须全局唯一。
if str(_INTEGRATION_DIR) not in sys.path:
    sys.path.append(str(_INTEGRATION_DIR))

import runtime  # ruff: ignore[module-import-not-at-top-of-file]

_INFRA_ERROR = runtime.probe_infra()


def _is_integration(item: pytest.Item) -> bool:
    return _INTEGRATION_DIR in Path(str(item.fspath)).parents


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """给本目录用例打上 integration 标记；依赖不可达时改为跳过。

    :param config: pytest 配置
    :param items: 已收集用例
    """
    _ = config
    skip = None
    if _INFRA_ERROR:
        skip = pytest.mark.skip(reason=f'PostgreSQL 或 Redis 不可达：{_INFRA_ERROR}')
    for item in items:
        if _is_integration(item):
            item.add_marker(pytest.mark.integration)
            if skip is not None:
                item.add_marker(skip)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """只收集到集成用例且依赖不可达时，拒绝以 0 退出。

    :param session: 当前会话
    :param exitstatus: 当前退出码
    """
    _ = exitstatus
    if not _INFRA_ERROR:
        return
    integration_items = [item for item in session.items if 'integration' in item.keywords]
    if not integration_items:
        return
    reporter = session.config.pluginmanager.get_plugin('terminalreporter')
    message = f'已跳过 {len(integration_items)} 个集成测试：PostgreSQL 或 Redis 不可达：{_INFRA_ERROR}'
    if reporter is not None:
        reporter.write_line(message)
    if len(integration_items) == len(session.items):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(scope='session')
def integration_database() -> runtime.PreparedDatabase:
    """本次 pytest 会话专用的测试库，结束时删除。"""
    prepared = runtime.prepare_database()
    try:
        yield prepared
    finally:
        runtime.drop_database(prepared.name)


@pytest.fixture(scope='session')
def integration_runtime(integration_database: runtime.PreparedDatabase) -> runtime.IntegrationRuntime:
    """导入应用并登录预置角色。整个会话只登录一次，避免验证码限流。

    :param integration_database: 已灌种子的测试库
    :return: 运行时
    """
    opened = runtime.IntegrationRuntime.open(integration_database)
    runtime.ACTIVE = opened
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture(scope='module')
def app(integration_runtime: runtime.IntegrationRuntime) -> object:
    """FastAPI 应用。集成用例需要导入应用时用这个，不要在收集阶段 import backend.main。

    :param integration_runtime: 运行时
    :return: 应用实例
    """
    return integration_runtime.app


@pytest.fixture(scope='module')
def role_accounts(integration_runtime: runtime.IntegrationRuntime) -> dict[str, runtime.RoleAccount]:
    """预置角色账号。键为 admin、salary_admin、site_owner、site_deputy、rider。

    :param integration_runtime: 运行时
    :return: 角色账号
    """
    return integration_runtime.accounts


@pytest.fixture(scope='module')
def role_tokens(role_accounts: dict[str, runtime.RoleAccount]) -> dict[str, dict[str, str]]:
    """预置角色的 Authorization 头。

    :param role_accounts: 角色账号
    :return: 请求头
    """
    return {key: account.headers for key, account in role_accounts.items()}


@pytest.fixture(scope='module')
def admin_token(role_tokens: dict[str, dict[str, str]]) -> dict[str, str]:
    """超管 token。密码与种子管理员相同。

    :param role_tokens: 全部角色请求头
    :return: Authorization 头
    """
    return role_tokens['admin']


@pytest.fixture(scope='module')
def salary_admin_token(role_tokens: dict[str, dict[str, str]]) -> dict[str, str]:
    """薪资管理员 token。

    :param role_tokens: 全部角色请求头
    :return: Authorization 头
    """
    return role_tokens['salary_admin']


@pytest.fixture(scope='module')
def site_owner_token(role_tokens: dict[str, dict[str, str]]) -> dict[str, str]:
    """站点负责人 token。种子数据里已绑定夹具站点 FXBASE。

    :param role_tokens: 全部角色请求头
    :return: Authorization 头
    """
    return role_tokens['site_owner']


@pytest.fixture(scope='module')
def site_deputy_token(role_tokens: dict[str, dict[str, str]]) -> dict[str, str]:
    """站点副负责人 token。菜单与站点负责人相同。

    :param role_tokens: 全部角色请求头
    :return: Authorization 头
    """
    return role_tokens['site_deputy']


@pytest.fixture(scope='module')
def rider_token(role_tokens: dict[str, dict[str, str]]) -> dict[str, str]:
    """骑手 token。对应夹具骑手 FXBASE001，可调用 /me。

    :param role_tokens: 全部角色请求头
    :return: Authorization 头
    """
    return role_tokens['rider']


@pytest.fixture
def client(integration_runtime: runtime.IntegrationRuntime) -> runtime.ApiClient:
    """每个用例一把的 API 客户端。用例结束回滚本用例写入。

    :param integration_runtime: 运行时
    :return: 同步包装的 httpx.AsyncClient
    """
    integration_runtime.begin_test()
    try:
        yield integration_runtime.client
    finally:
        integration_runtime.rollback_test()

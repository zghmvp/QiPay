"""无库：api/v1 依赖合同 + rs:me:* 残留。"""

from backend.plugin.rider_salary.tests.rbac_support import (
    API_V1,
    JWT_ONLY_OBSERVATION,
    READ_HUNG_ON_WRITE_SNAPSHOT,
    SQL_ROOT,
    jwt_only_paths,
    read_hung_on_write,
    scan_api_gates,
)


def test_rbac_api_jwt_only_allowlist() -> None:
    routes = scan_api_gates()
    jwt_only = jwt_only_paths(routes)
    unexpected = {path for path in jwt_only if not path.startswith('/me')}
    extra = unexpected - JWT_ONLY_OBSERVATION
    missing_observed = JWT_ONLY_OBSERVATION - unexpected
    assert not extra, f'新增 JWT-only 管理端路由（须挂 RBAC 或写入观察名单）：{sorted(extra)}'
    # 观察名单条目被补上 RBAC 后应从名单移除；缺项说明扫描漏路径
    assert not missing_observed, f'文档化 JWT-only 观察名单未扫到：{sorted(missing_observed)}'


def test_rbac_api_read_perm_mismatch() -> None:
    routes = scan_api_gates()
    found = read_hung_on_write(routes)
    extra = {key: perm for key, perm in found.items() if READ_HUNG_ON_WRITE_SNAPSHOT.get(key) != perm}
    missing = {key: perm for key, perm in READ_HUNG_ON_WRITE_SNAPSHOT.items() if found.get(key) != perm}
    assert extra == {} and missing == {}, (
        f'读挂写权限合同变化（修复后请改 READ_HUNG_ON_WRITE_SNAPSHOT）： extra={extra} missing={missing} actual={found}'
    )


def test_rbac_no_rs_me_star() -> None:
    for path in SQL_ROOT.glob('*/*.sql'):
        text = path.read_text(encoding='utf-8')
        assert 'rs:me:' not in text, f'{path} 含 rs:me:*'
    for path in API_V1.glob('*.py'):
        text = path.read_text(encoding='utf-8')
        assert 'rs:me:' not in text, f'{path} 含 rs:me:*'

"""只挂 JWT 的管理端接口补 RBAC。

订单、批次的 4 个 GET 与引擎的 6 个接口：骑手一律 403。
薪资管理员可读写两端；站点负责人与副负责人只能读订单；超管免校验。
账号和 token 来自集成基座，不在开发库建临时用户。
"""

import pytest

from runtime import ApiClient

_READS: tuple[tuple[str, str, dict | None, str], ...] = (
    ('GET', '/rider-salary/orders', None, 'list'),
    ('GET', '/rider-salary/orders/9223372036854775806', None, 'detail'),
    ('GET', '/rider-salary/import-batches', None, 'list'),
    ('GET', '/rider-salary/import-batches/9223372036854775806', None, 'detail'),
)
_ENGINES: tuple[tuple[str, str, dict | None, str], ...] = (
    ('GET', '/rider-salary/engine/fields', None, 'engine'),
    ('GET', '/rider-salary/engine/operators', None, 'engine'),
    ('GET', '/rider-salary/engine/functions', None, 'engine'),
    ('GET', '/rider-salary/engine/formula-templates', None, 'engine'),
    ('POST', '/rider-salary/engine/validate', {'stage': 'per_order'}, 'engine'),
    ('POST', '/rider-salary/engine/evaluate-sample', {'stage': 'per_order', 'context': {}}, 'engine'),
)

# 角色 → (订单读接口放行, 引擎接口放行)。超管对应基座 admin。
_ACCESS: dict[str, tuple[bool, bool]] = {
    'admin': (True, True),
    'salary_admin': (True, True),
    'site_owner': (True, False),
    'site_deputy': (True, False),
    'rider': (False, False),
}


def _cases() -> list[tuple[str, str, str, dict | None, str, bool]]:
    rows: list[tuple[str, str, str, dict | None, str, bool]] = []
    for role, (read_ok, engine_ok) in _ACCESS.items():
        for method, path, body, kind in _READS:
            rows.append((role, method, path, body, kind, read_ok))
        for method, path, body, kind in _ENGINES:
            rows.append((role, method, path, body, kind, engine_ok))
    return rows


@pytest.mark.parametrize(
    ('role', 'method', 'path', 'body', 'kind', 'allowed'),
    _cases(),
)
def test_ten_endpoints_rbac_by_role(
    client: ApiClient,
    role_tokens: dict[str, dict[str, str]],
    role: str,
    method: str,
    path: str,
    body: dict | None,
    kind: str,
    *,
    allowed: bool,
) -> None:
    """按角色检查订单、批次和引擎接口的放行与拒绝。"""
    response = client.request(method, path, headers=role_tokens[role], json=body)
    payload = response.json()
    if not allowed:
        assert response.status_code == 403, payload
        assert payload['code'] == 403
        return
    if kind == 'detail':
        assert response.status_code in {200, 404}, payload
        assert payload['code'] == response.status_code
        return
    assert response.status_code == 200, payload
    assert payload['code'] == 200

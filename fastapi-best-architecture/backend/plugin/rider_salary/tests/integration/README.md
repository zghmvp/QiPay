# 集成测试基座

走真实 HTTP 接口，使用独立的 PostgreSQL 库和带前缀的 Redis 键。开发库 `fba` 不会被写入。

## 命令

在 `fastapi-best-architecture` 目录：

```bash
# 默认：纯函数和集成一起跑
uv run --python 3.12 pytest backend/plugin/rider_salary/tests -q

# 只跑集成
uv run --python 3.12 pytest backend/plugin/rider_salary/tests -q -m integration

# 只跑纯函数
uv run --python 3.12 pytest backend/plugin/rider_salary/tests -q -m "not integration"
```

`tests/integration/` 下的用例会自动带上 `integration` 标记，不必再手写装饰器。默认命令不加 `-m`，两类都会跑。

PostgreSQL 或 Redis 不可达时，集成用例记为跳过，输出里有「已跳过 N 个集成测试」和原因；纯函数测试继续跑。只跑 `-m integration` 时进程以非 0 退出，避免 0 个用例假绿。应用在夹具里导入，不在收集阶段导入 `backend.main`。

## 夹具

| 夹具 | 作用域 | 内容 |
|---|---|---|
| `app` | 模块 | FastAPI 应用。请求请用下面的 `client`，不要再包 Starlette TestClient |
| `client` | 用例 | `httpx.AsyncClient` 的同步包装，基址是 `/api/v1`。方法有 `get` / `post` / `put` / `delete` / `request` |
| `admin_token` | 模块 | 超管 `admin`，口令 `123456` |
| `salary_admin_token` | 模块 | 薪资管理员 `it_salary_admin` |
| `site_owner_token` | 模块 | 站点负责人 `it_site_owner`，已绑定夹具站点 `FXBASE` |
| `site_deputy_token` | 模块 | 站点副负责人 `it_site_deputy`，菜单与站点负责人相同 |
| `rider_token` | 模块 | 骑手 `it_rider`，对应工号 `FXBASE001`，走 `/me` |
| `role_tokens` | 模块 | 上面五个请求头，键为 `admin` / `salary_admin` / `site_owner` / `site_deputy` / `rider` |
| `role_accounts` | 模块 | 同键的账号对象，含 `username`、`user_id`、`headers` |

请求头就是 `{'Authorization': 'Bearer ...'}`，直接传给 `headers=`。

每个用例包在外层事务里，结束回滚。种子账号、夹具站点和夹具骑手在建库时写入，不会被回滚。用例之间不要依赖彼此创建的业务数据。

`client` 必须在基座自己的事件循环上使用，测试函数写成普通同步函数。不要在用例里再 `asyncio.run`、另起 `httpx.AsyncClient`，或用 Starlette `TestClient`。`TestClient` 会进入应用 lifespan，在另一个事件循环上初始化全局 Redis，随后全量测试会出现 `Event loop is closed`。

## 工厂

`factories.py` 都走 API，第一个参数是 `client`，第二个是 token 头。

- `create_site` / `create_rider`：创建后按编码或工号查回。
- `create_c01_plan`：管理端预设 C01「纯按单（5 元/单）」，每有效单 5 元。返回 `plan_id`、`version_id`，此时还是草稿。
- `activate_plan`：用至少一笔已完成订单做试算，再启用。启用前必须先试算。
- `bind_plan`：把已启用版本绑到骑手。算薪前再绑定，避免草稿被标成需要重算。
- `generate_month`：生成某月周期，返回站点级那一条（`rider_id == 0`）。
- `import_completed_orders`：CSV 导入。`rows` 的每一行是订单号、下单时间、送达时间、金额。
- `calculate_period` / `lock_period` / `mark_paid` / `get_period`。
- `bind_site_manager`：把 `role_accounts['site_owner'].user_id` 绑到新站点后，负责人 token 才能看到该站。
- `expect_ok`：断言 HTTP 和业务码都是 200，返回 `data`。

## 写一条新场景

文件放在本目录，文件名 `test_<场景>.py`。插件测试按文件名导入，这个名字不能和 `tests/` 下其他文件重名。函数保持同步，参数写上类型。现成例子是 `test_api_period_lifecycle.py`。

已有接口用例直接用 `client` 和 `role_tokens`。`test_jwt_only_rbac.py` 就是从独立 TestClient 迁过来的：订单、导入批次和公式引擎按角色断言 200 或 403，账号来自基座种子，不写开发库。`client` 只在本目录生效。

```python
from factories import bind_site_manager, create_rider, create_site, expect_ok
from runtime import ApiClient, RoleAccount


def test_example(
    client: ApiClient,
    admin_token: dict[str, str],
    site_owner_token: dict[str, str],
    role_accounts: dict[str, RoleAccount],
) -> None:
    """负责人绑定新站点后能看见该站。"""
    site = create_site(client, admin_token, name='场景站点')
    rider = create_rider(client, admin_token, site_id=site['id'])
    bind_site_manager(
        client,
        admin_token,
        site_id=site['id'],
        user_id=role_accounts['site_owner'].user_id,
    )
    visible = expect_ok(client.get('/rider-salary/sites', headers=site_owner_token, params={'page': 1, 'size': 50}))
    assert any(item['id'] == site['id'] for item in visible['items'])
    assert rider['site_id'] == site['id']
```

阶段 0 的服务层单测迁过来时：把直接调 service 改成上面的工厂或 `client` 请求，断言 HTTP 状态和响应体。不要再连开发库 `fba`。

多个子代理同时跑 pytest 时，每次会话的库名带进程号和随机串，Redis 键也带当次前缀，互不覆盖。本轮结束会删库、删键。异常中断留下的库名以 `fba_it_` 开头，确认没有进程使用后再手工 `DROP DATABASE`。

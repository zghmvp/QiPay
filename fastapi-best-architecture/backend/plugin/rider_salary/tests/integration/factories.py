"""集成测试工厂。通过 HTTP 创建站点、骑手、方案、订单和周期。"""

import csv
import io
import uuid

from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

# 与管理端 constants/plan-presets.ts 的 C01「纯按单（5 元/单）」一致。
C01_NAME = '纯按单（5 元/单）'
C01_FORMULA = {'类型': '固定金额', '金额': 5}


def expect_ok(response: Any) -> Any:
    """断言统一响应成功并返回 data。

    :param response: httpx 响应
    :return: 响应体里的 data
    """
    try:
        body = response.json()
    except Exception as exc:
        raise AssertionError(response.text) from exc
    if response.status_code != 200 or body.get('code') != 200:
        raise AssertionError(f'HTTP {response.status_code} {body}')
    return body.get('data')


def create_site(
    client: Any,
    headers: dict[str, str],
    *,
    code: str | None = None,
    name: str = '集成测试站点',
    settle_cycle: str = 'month',
) -> dict[str, Any]:
    """创建站点并按编码查回。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param code: 站点编码，空则自动生成
    :param name: 站点名称
    :param settle_cycle: 结算周期类型
    :return: 站点详情
    """
    site_code = code or f'IT{uuid.uuid4().hex[:8].upper()}'
    expect_ok(
        client.post(
            '/rider-salary/sites',
            headers=headers,
            json={
                'code': site_code,
                'name': name,
                'settle_cycle': settle_cycle,
                'status': 'enable',
            },
        )
    )
    return find_site(client, headers, site_code)


def find_site(client: Any, headers: dict[str, str], code: str) -> dict[str, Any]:
    """按编码查找站点。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param code: 站点编码
    :return: 站点详情
    """
    data = expect_ok(client.get('/rider-salary/sites', headers=headers, params={'code': code, 'page': 1, 'size': 20}))
    for item in data['items']:
        if item['code'] == code:
            return item
    raise AssertionError(f'未找到站点 {code}')


def create_rider(
    client: Any,
    headers: dict[str, str],
    *,
    site_id: int,
    job_no: str | None = None,
    name: str = '集成测试骑手',
    hire_date: str = '2026-09-01',
    employ_type: str = 'part_time',
) -> dict[str, Any]:
    """创建在职骑手并按工号查回。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param site_id: 站点 ID
    :param job_no: 工号，空则自动生成
    :param name: 姓名
    :param hire_date: 入职日期
    :param employ_type: 用工类型
    :return: 骑手详情
    """
    rider_job_no = job_no or f'IT{uuid.uuid4().hex[:8].upper()}'
    expect_ok(
        client.post(
            '/rider-salary/riders',
            headers=headers,
            json={
                'job_no': rider_job_no,
                'name': name,
                'site_id': site_id,
                'employ_type': employ_type,
                'hire_date': hire_date,
                'status': 'on_job',
            },
        )
    )
    data = expect_ok(
        client.get(
            '/rider-salary/riders',
            headers=headers,
            params={'site_id': site_id, 'keyword': rider_job_no, 'page': 1, 'size': 20},
        )
    )
    for item in data['items']:
        if item['job_no'] == rider_job_no:
            return item
    raise AssertionError(f'未找到骑手 {rider_job_no}')


def subject_id(client: Any, headers: dict[str, str], code: str) -> int:
    """按科目编码取 ID。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param code: 科目编码
    :return: 科目 ID
    """
    rows = expect_ok(client.get('/rider-salary/subjects/all', headers=headers))
    for row in rows:
        if row['code'] == code:
            return int(row['id'])
    raise AssertionError(f'缺少科目 {code}')


def create_c01_plan(client: Any, headers: dict[str, str], *, code: str | None = None) -> dict[str, int]:
    """创建 C01 纯按单方案的草稿版本和方案项，尚未启用。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param code: 方案编码，空则自动生成
    :return: plan_id 与 version_id
    """
    plan_code = code or f'C01{uuid.uuid4().hex[:6].upper()}'
    plan = expect_ok(
        client.post(
            '/rider-salary/plans',
            headers=headers,
            json={
                'code': plan_code,
                'name': C01_NAME,
                'short_name': '按单',
                'color': '#1677ff',
                'description': '众包兼职，每有效单固定 5 元，无底薪无阶梯。',
                'status': 'enable',
            },
        )
    )
    version = expect_ok(
        client.post(
            '/rider-salary/plan-versions',
            headers=headers,
            json={'plan_id': plan['id'], 'mode_tag': 'per_order', 'remark': 'C01'},
        )
    )
    base_subject = subject_id(client, headers, 'BASE_UNIT_PRICE')
    expect_ok(
        client.put(
            f'/rider-salary/plan-versions/{version["id"]}/items',
            headers=headers,
            json=[
                {
                    'subject_id': base_subject,
                    'name': '基础单价',
                    'stage': 'per_order',
                    'sort_order': 0,
                    'formula_json': C01_FORMULA,
                    'enabled': True,
                }
            ],
        )
    )
    return {'plan_id': int(plan['id']), 'version_id': int(version['id'])}


def ensure_completed_order_for_trial(
    client: Any,
    headers: dict[str, str],
    *,
    rider_id: int,
    start_date: str,
    end_date: str,
) -> int | None:
    """试算区间里没有已完成订单时补一笔，返回新建订单 ID。已有则返回空。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param rider_id: 试算骑手
    :param start_date: 试算开始日期
    :param end_date: 试算结束日期
    :return: 新建订单 ID；区间内已有已完成订单时为空
    """
    existing = expect_ok(
        client.get(
            '/rider-salary/orders',
            headers=headers,
            params={
                'rider_id': rider_id,
                'date_from': start_date,
                'date_to': end_date,
                'status': 'completed',
                'page': 1,
                'size': 1,
            },
        )
    )
    if existing.get('items'):
        return None
    rider = expect_ok(client.get(f'/rider-salary/riders/{rider_id}', headers=headers))
    created = expect_ok(
        client.post(
            '/rider-salary/orders',
            headers=headers,
            json={
                'order_no': f'TR{uuid.uuid4().hex[:12].upper()}',
                'site_id': rider['site_id'],
                'rider_id': rider_id,
                'distance_km': '1.00',
                'weight_jin': '1.00',
                'order_time': f'{start_date}T12:00:00',
                'deliver_time': f'{start_date}T12:20:00',
                'status': 'completed',
                'amount': '10.00',
                'remark': '试算占位',
            },
        )
    )
    return int(created['id'])


def _delete_trial_placeholder(client: Any, headers: dict[str, str], order_id: int) -> None:
    """删掉仅为通过试算闸门补上的订单，避免改后续算薪金额。"""
    expect_ok(
        client.delete(
            f'/rider-salary/orders/{order_id}',
            headers=headers,
            json={'reason': '试算占位订单用完即删'},
        )
    )


def activate_plan(
    client: Any,
    headers: dict[str, str],
    *,
    version_id: int,
    rider_id: int,
    start_date: str,
    end_date: str,
) -> None:
    """用指定骑手和日期试算后启用方案版本。区间内没有已完成订单时先补一笔，启用后删掉。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param version_id: 方案版本 ID
    :param rider_id: 试算骑手
    :param start_date: 试算开始日期
    :param end_date: 试算结束日期
    """
    placeholder_id = ensure_completed_order_for_trial(
        client,
        headers,
        rider_id=rider_id,
        start_date=start_date,
        end_date=end_date,
    )
    try:
        expect_ok(
            client.post(
                f'/rider-salary/plan-versions/{version_id}/trial',
                headers=headers,
                json={'rider_id': rider_id, 'start_date': start_date, 'end_date': end_date},
            )
        )
        expect_ok(client.post(f'/rider-salary/plan-versions/{version_id}/activate', headers=headers))
    finally:
        if placeholder_id is not None:
            _delete_trial_placeholder(client, headers, placeholder_id)


def bind_plan(
    client: Any,
    headers: dict[str, str],
    *,
    rider_id: int,
    version_id: int,
    start_date: str,
    binding_type: str = 'default',
) -> None:
    """给骑手绑定已启用的方案版本。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param rider_id: 骑手 ID
    :param version_id: 方案版本 ID
    :param start_date: 生效开始日期
    :param binding_type: 绑定类型
    """
    expect_ok(
        client.post(
            f'/rider-salary/riders/{rider_id}/bindings',
            headers=headers,
            json={
                'plan_version_id': version_id,
                'binding_type': binding_type,
                'start_date': start_date,
            },
        )
    )


def bind_site_manager(
    client: Any,
    headers: dict[str, str],
    *,
    site_id: int,
    user_id: int,
    role: str = 'owner',
) -> None:
    """覆盖站点负责人。站点负责人 token 只能看到这里绑定过的站点。

    :param client: 基座客户端
    :param headers: 调用方 token，需要 ``rs:site:manager``
    :param site_id: 站点 ID
    :param user_id: 用户 ID
    :param role: owner 或 deputy
    """
    expect_ok(
        client.put(
            f'/rider-salary/sites/{site_id}/managers',
            headers=headers,
            json=[{'user_id': user_id, 'role': role}],
        )
    )


def generate_month(client: Any, headers: dict[str, str], *, site_id: int, month: str) -> dict[str, Any]:
    """生成某月结算周期，并返回站点级那一条。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param site_id: 站点 ID
    :param month: YYYY-MM
    :return: 生成结果里的站点级周期
    """
    data = expect_ok(
        client.post('/rider-salary/periods/generate', headers=headers, json={'site_id': site_id, 'month': month})
    )
    site_level = [item for item in data['items'] if item['rider_id'] == 0]
    if len(site_level) != 1 or not site_level[0].get('id'):
        raise AssertionError(f'没有生成唯一的站点级周期：{data}')
    return site_level[0]


def import_completed_orders(
    client: Any,
    headers: dict[str, str],
    *,
    site_id: int,
    site_code: str,
    job_no: str,
    rows: list[tuple[str, str, str, str]],
) -> dict[str, Any]:
    """按 CSV 导入已完成订单。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param site_id: 站点 ID
    :param site_code: 站点编码
    :param job_no: 骑手工号
    :param rows: 每行是订单号、下单时间、送达时间、金额
    :return: 导入结果
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        '站点编码',
        '骑手工号',
        '订单号',
        '配送距离(公里)',
        '商品重量(斤)',
        '下单时间',
        '送达时间',
        '订单状态',
        '订单金额',
        '备注',
    ])
    for order_no, order_time, deliver_time, amount in rows:
        writer.writerow([site_code, job_no, order_no, '3.50', '5.00', order_time, deliver_time, '已完成', amount, ''])
    content = buffer.getvalue().encode('utf-8')
    return expect_ok(
        client.post(
            '/rider-salary/orders/import',
            headers=headers,
            data={'site_id': str(site_id), 'skip_errors': 'false', 'auto_recalc': 'false'},
            files={'file': ('orders.csv', content, 'text/csv')},
        )
    )


def calculate_period(client: Any, headers: dict[str, str], period_id: int) -> dict[str, Any]:
    """同步计算一个周期。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param period_id: 周期 ID
    :return: 算薪结果
    """
    return expect_ok(client.post(f'/rider-salary/periods/{period_id}/calculate', headers=headers, json={}))


def lock_period(client: Any, headers: dict[str, str], period_id: int, reason: str) -> None:
    """锁账。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param period_id: 周期 ID
    :param reason: 锁账原因
    """
    expect_ok(client.post(f'/rider-salary/periods/{period_id}/lock', headers=headers, json={'reason': reason}))


def mark_paid(client: Any, headers: dict[str, str], period_id: int, reason: str) -> dict[str, Any]:
    """标记发薪。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param period_id: 周期 ID
    :param reason: 操作原因
    :return: 标记结果
    """
    return expect_ok(
        client.post(f'/rider-salary/periods/{period_id}/mark-paid', headers=headers, json={'reason': reason})
    )


def get_period(client: Any, headers: dict[str, str], period_id: int) -> dict[str, Any]:
    """读取周期详情。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param period_id: 周期 ID
    :return: 周期详情
    """
    return expect_ok(client.get(f'/rider-salary/periods/{period_id}', headers=headers))


def money(value: object) -> Decimal:
    """把响应里的金额转成两位小数。

    :param value: 接口返回的金额
    :return: 金额
    """
    return Decimal(str(value)).quantize(Decimal('0.01'))


RIDER_PASSWORD = 'Rider@123456'
_EFFECTIVE_STATUS = frozenset({'draft', 'finalized', 'paid'})


def expect_error(response: Any, status: int = 400) -> str:
    """断言业务失败，返回中文 msg。

    :param response: httpx 响应
    :param status: 期望的 HTTP 与业务码
    :return: 错误消息
    """
    try:
        body = response.json()
    except Exception as exc:
        raise AssertionError(response.text) from exc
    if response.status_code != status or body.get('code') != status:
        raise AssertionError(f'期望 {status}，实际 HTTP {response.status_code} {body}')
    return str(body.get('msg') or '')


def month_bounds(month: str) -> tuple[str, str]:
    """某月的起止日期。

    :param month: YYYY-MM
    :return: 开始日、结束日
    """
    year_text, month_text = month.split('-')
    year, mon = int(year_text), int(month_text)
    start = f'{year:04d}-{mon:02d}-01'
    end_month = date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)
    end = (end_month - timedelta(days=1)).isoformat()
    return start, end


def order_row(order_no: str, day: str, amount: str = '20.00') -> tuple[str, str, str, str]:
    """拼一条已完成订单导入行。

    :param order_no: 订单号
    :param day: 业务日 YYYY-MM-DD
    :param amount: 订单金额
    :return: 订单号、下单时间、送达时间、金额
    """
    return (order_no, f'{day} 12:00:00', f'{day} 12:20:00', amount)


def create_rider_with_phone(
    client: Any,
    headers: dict[str, str],
    *,
    site_id: int,
    phone: str,
    job_no: str | None = None,
    name: str = '集成测试骑手',
    hire_date: str = '2026-09-01',
    employ_type: str = 'part_time',
) -> dict[str, Any]:
    """创建带手机号的在职骑手。已有 ``create_rider`` 不接收手机号，这里另起一个函数。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param site_id: 站点 ID
    :param phone: 手机号
    :param job_no: 工号，空则自动生成
    :param name: 姓名
    :param hire_date: 入职日期
    :param employ_type: 用工类型
    :return: 骑手详情
    """
    rider_job_no = job_no or f'IT{uuid.uuid4().hex[:8].upper()}'
    expect_ok(
        client.post(
            '/rider-salary/riders',
            headers=headers,
            json={
                'job_no': rider_job_no,
                'name': name,
                'phone': phone,
                'site_id': site_id,
                'employ_type': employ_type,
                'hire_date': hire_date,
                'status': 'on_job',
            },
        )
    )
    data = expect_ok(
        client.get(
            '/rider-salary/riders',
            headers=headers,
            params={'site_id': site_id, 'keyword': rider_job_no, 'page': 1, 'size': 20},
        )
    )
    for item in data['items']:
        if item['job_no'] == rider_job_no:
            return item
    raise AssertionError(f'未找到骑手 {rider_job_no}')


def create_plan(
    client: Any,
    headers: dict[str, str],
    *,
    name: str,
    short_name: str,
    items: list[dict[str, Any]],
    code: str | None = None,
    mode_tag: str = 'custom',
) -> dict[str, int]:
    """创建草稿方案版本并写入方案项。``items`` 用 ``subject_code`` 指向科目。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param name: 方案名称
    :param short_name: 短名
    :param items: 方案项，含 subject_code、name、stage、formula_json、sort_order
    :param code: 方案编码，空则自动生成
    :param mode_tag: 版本标签
    :return: plan_id 与 version_id
    """
    plan_code = code or f'PL{uuid.uuid4().hex[:6].upper()}'
    plan = expect_ok(
        client.post(
            '/rider-salary/plans',
            headers=headers,
            json={
                'code': plan_code,
                'name': name,
                'short_name': short_name,
                'color': '#1677ff',
                'description': name,
                'status': 'enable',
            },
        )
    )
    version = expect_ok(
        client.post(
            '/rider-salary/plan-versions',
            headers=headers,
            json={'plan_id': plan['id'], 'mode_tag': mode_tag, 'remark': name},
        )
    )
    payload = [
        {
            'subject_id': subject_id(client, headers, item['subject_code']),
            'name': item['name'],
            'stage': item['stage'],
            'sort_order': item['sort_order'],
            'formula_json': item['formula_json'],
            'enabled': True,
        }
        for item in items
    ]
    expect_ok(
        client.put(
            f'/rider-salary/plan-versions/{version["id"]}/items',
            headers=headers,
            json=payload,
        )
    )
    return {'plan_id': int(plan['id']), 'version_id': int(version['id'])}


class _SharedRequestSession:
    """把一次请求里先后打开的会话收成同一个事务。"""

    def __init__(self, begin: Any) -> None:
        self._begin = begin
        self._depth = 0
        self._context: Any = None
        self._session: Any = None
        self._error: BaseException | None = None

    async def enter(self) -> Any:
        if self._session is None:
            self._context = self._begin()
            self._session = await self._context.__aenter__()
            self._error = None
        self._depth += 1
        return self._session

    async def leave(self, error: BaseException | None) -> None:
        if error is not None:
            self._error = error
        self._depth -= 1
        if self._depth > 0:
            return
        await self._close()

    async def _close(self) -> None:
        context = self._context
        err = self._error
        self._context = None
        self._session = None
        self._error = None
        self._depth = 0
        if context is None:
            return
        if err is None:
            await context.__aexit__(None, None, None)
            return
        await context.__aexit__(type(err), err, err.__traceback__)

    async def read(self) -> AsyncGenerator[Any, None]:
        async for session in self._yield():
            yield session

    async def _yield(self) -> AsyncGenerator[Any, None]:
        session = await self.enter()
        error: BaseException | None = None
        try:
            yield session
        except BaseException as exc:
            error = exc
            raise
        finally:
            await self.leave(error)

    async def write(self) -> AsyncGenerator[Any, None]:
        async for session in self._yield():
            yield session


@contextmanager
def use_shared_db_session() -> Generator[None, None, None]:
    """同一请求里的只读会话和事务会话共用一个 Session。

    基座把全部会话绑在同一条连接上。``/me`` 写接口同时依赖这两种会话时，
    后关闭的只读会话会回滚写会话的 savepoint，提交时报 savepoint 不存在。
    """
    import runtime

    from backend.database import db as db_mod

    app = runtime.ACTIVE.app
    holder = _SharedRequestSession(db_mod.async_db_session.begin)
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[db_mod.get_db] = holder.read
    app.dependency_overrides[db_mod.get_db_transaction] = holder.write
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def _clear_captcha_rate_limit() -> None:
    """清掉本次运行的验证码限流桶。会话登录已用完每分钟 5 次额度。"""
    import redis

    from backend.core.conf import settings

    redis_client = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD or None,
        db=settings.REDIS_DATABASE,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        keys = list(redis_client.scan_iter(match=f'{settings.REQUEST_LIMITER_REDIS_PREFIX}*'))
        if keys:
            redis_client.delete(*keys)
    finally:
        redis_client.close()


def login_username(client: Any, username: str, password: str) -> dict[str, str]:
    """用验证码登录，验证码从本次测试的 Redis 前缀读取。

    :param client: 基座客户端
    :param username: 用户名
    :param password: 密码
    :return: Authorization 头
    """
    import redis

    from backend.core.conf import settings

    _clear_captcha_rate_limit()
    captcha = client.get('/auth/captcha')
    body = captcha.json()
    if captcha.status_code != 200 or body.get('code') != 200:
        raise AssertionError(captcha.text)
    payload: dict[str, str] = {'username': username, 'password': password}
    data = body.get('data') or {}
    if data.get('is_enabled', True):
        redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD or None,
            db=settings.REDIS_DATABASE,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        try:
            code = redis_client.get(f'{settings.LOGIN_CAPTCHA_REDIS_PREFIX}:{data["uuid"]}')
        finally:
            redis_client.close()
        if not code:
            raise AssertionError(f'Redis 中没有验证码：{username}')
        payload['uuid'] = data['uuid']
        payload['captcha'] = code
    response = client.post('/auth/login', json=payload)
    logged = response.json()
    if response.status_code != 200 or logged.get('code') != 200:
        raise AssertionError(f'登录失败 {username}：{response.text}')
    token = logged['data']['access_token']
    token_type = logged['data'].get('token_type') or 'Bearer'
    return {'Authorization': f'{token_type} {token}'}


def open_rider_account(
    client: Any,
    headers: dict[str, str],
    *,
    rider_id: int,
    job_no: str,
    password: str = RIDER_PASSWORD,
) -> dict[str, str]:
    """开通骑手账号、登录，并完成首次改密。

    开户会要求首次登录改密。这里立刻改成另一口令并保留当前登录，后续 /me 才能放行。

    :param client: 基座客户端
    :param headers: 具备开户权限的 token
    :param rider_id: 骑手 ID
    :param job_no: 工号，即登录名
    :param password: 初始密码
    :return: 骑手 Authorization 头
    """
    expect_ok(
        client.post(
            f'/rider-salary/riders/{rider_id}/open-account',
            headers=headers,
            json={'password': password, 'reason': '场景开户'},
        )
    )
    rider_headers = login_username(client, job_no, password)
    changed = 'ItChanged#1a' if password != 'ItChanged#1a' else 'ItChanged#2b'
    # /me 改密同时依赖只读会话和事务会话，单连接上必须合成一个，否则提交时保存点不存在。
    with use_shared_db_session():
        expect_ok(
            client.put(
                '/rider-salary/me/password',
                headers=rider_headers,
                json={
                    'old_password': password,
                    'new_password': changed,
                    'confirm_password': changed,
                },
            )
        )
    return rider_headers


def provision_c01_month(
    client: Any,
    headers: dict[str, str],
    *,
    month: str,
    orders: list[tuple[str, str, str, str]],
    hire_date: str = '2026-01-01',
    rider_name: str = '场景骑手',
    site_name: str = '场景站点',
) -> dict[str, Any]:
    """站点、骑手、C01、月周期、订单、试算启用和绑定。尚未算薪。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param month: YYYY-MM
    :param orders: 导入行
    :param hire_date: 入职日期
    :param rider_name: 骑手姓名
    :param site_name: 站点名称
    :return: site、rider、plan、period
    """
    site = create_site(client, headers, name=site_name)
    rider = create_rider(client, headers, site_id=site['id'], name=rider_name, hire_date=hire_date)
    plan = create_c01_plan(client, headers)
    period = generate_month(client, headers, site_id=site['id'], month=month)
    imported = import_completed_orders(
        client,
        headers,
        site_id=site['id'],
        site_code=site['code'],
        job_no=rider['job_no'],
        rows=orders,
    )
    if imported['success_rows'] != len(orders):
        raise AssertionError(imported)
    start, end = month_bounds(month)
    activate_plan(
        client,
        headers,
        version_id=plan['version_id'],
        rider_id=rider['id'],
        start_date=start,
        end_date=end,
    )
    bind_plan(client, headers, rider_id=rider['id'], version_id=plan['version_id'], start_date=start)
    return {'site': site, 'rider': rider, 'plan': plan, 'period': period}


def reverse_period(client: Any, headers: dict[str, str], period_id: int, reason: str = '场景反冲') -> dict[str, Any]:
    """反冲一个已锁账或已发薪周期。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param period_id: 周期 ID
    :param reason: 原因
    :return: 反冲结果
    """
    return expect_ok(
        client.post(f'/rider-salary/periods/{period_id}/reverse', headers=headers, json={'reason': reason})
    )


def carry_forward_period(
    client: Any,
    headers: dict[str, str],
    period_id: int,
    *,
    rider_ids: list[int] | None = None,
    reason: str = '金额无需变化',
) -> dict[str, Any]:
    """为已反冲骑手沿用原单。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param period_id: 周期 ID
    :param rider_ids: 指定骑手，空表示全部缺补发单的骑手
    :param reason: 原因
    :return: 沿用结果
    """
    body: dict[str, Any] = {'reason': reason}
    if rider_ids is not None:
        body['rider_ids'] = rider_ids
    return expect_ok(client.post(f'/rider-salary/periods/{period_id}/carry-forward', headers=headers, json=body))


def period_payrolls(client: Any, headers: dict[str, str], period_id: int) -> list[dict[str, Any]]:
    """读取周期详情里的薪资单。

    :param client: 基座客户端
    :param headers: 调用方 token
    :param period_id: 周期 ID
    :return: 薪资单摘要
    """
    detail = get_period(client, headers, period_id)
    return list(detail.get('payrolls') or [])


def effective_payroll(payrolls: list[dict[str, Any]], rider_id: int) -> dict[str, Any] | None:
    """挑出该骑手当前有效薪资单：非作废、非反冲、未被反冲，取计算轮次最新的一张。

    :param payrolls: 周期内薪资单
    :param rider_id: 骑手 ID
    :return: 有效单；还没有则返回空
    """
    rows = [
        row
        for row in payrolls
        if row['rider_id'] == rider_id
        and row['status'] in _EFFECTIVE_STATUS
        and row['kind'] != 'reversal'
        and not row['reversed']
    ]
    if not rows:
        return None
    rows.sort(key=lambda row: (int(row.get('calc_version') or 0), int(row['id'])), reverse=True)
    return rows[0]


def live_net(payrolls: list[dict[str, Any]], rider_id: int | None = None) -> Decimal:
    """未作废薪资单的实发合计。原单与反冲单抵消后等于仍有效的单据。

    :param payrolls: 薪资单
    :param rider_id: 只统计该骑手；空则全期
    :return: 实发合计
    """
    total = Decimal('0.00')
    for row in payrolls:
        if rider_id is not None and row['rider_id'] != rider_id:
            continue
        if row['status'] == 'voided':
            continue
        total += money(row['net'])
    return money(total)

"""活 API 夹具：SU/SA/SO/RD 登录与两站最小数据。"""

from __future__ import annotations

import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from dataclasses import dataclass, field
from typing import Any

from openpyxl import Workbook

API_URL = os.environ.get('RIDER_SALARY_API_URL', os.environ.get('API_URL', 'http://127.0.0.1:8000')).rstrip('/')
STAFF_PASS = os.environ.get('RIDER_SALARY_STAFF_PASS', 'Rider@123456')
SU_USERS = (
    (os.environ.get('RIDER_SALARY_SU_USER', 'admin'), os.environ.get('RIDER_SALARY_SU_PASS', 'admin')),
    ('admin', '123456'),
    ('admin', 'admin'),
)

PREFIX = '/api/v1/rider-salary'
SYS = '/api/v1'


@dataclass
class HttpResult:
    status: int
    body: Any
    headers: dict[str, str]
    raw: bytes

    @property
    def code(self) -> int | None:
        if isinstance(self.body, dict) and 'code' in self.body:
            try:
                return int(self.body['code'])
            except (TypeError, ValueError):
                return None
        return None

    @property
    def msg(self) -> str:
        if isinstance(self.body, dict):
            return str(self.body.get('msg') or '')
        return ''

    @property
    def data(self) -> Any:
        if isinstance(self.body, dict):
            return self.body.get('data')
        return None

    @property
    def items(self) -> list[Any]:
        data = self.data
        if isinstance(data, dict):
            return list(data.get('items') or [])
        if isinstance(data, list):
            return data
        return []

    @property
    def total(self) -> int:
        data = self.data
        if isinstance(data, dict) and data.get('total') is not None:
            return int(data['total'])
        return len(self.items)


def _http_url(url: str) -> str:
    if not url.startswith(('http://', 'https://')):
        raise ValueError(f'仅允许 http(s) URL：{url}')
    return url


def api_reachable(timeout: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(_http_url(f'{API_URL}/docs'), timeout=timeout)  # ruff: ignore[suspicious-url-open-usage]
    except Exception:
        return False
    else:
        return True


def _request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    json_body: Any = None,
    form: dict[str, str] | None = None,
    file_field: tuple[str, str, bytes, str] | None = None,
    query: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> HttpResult:
    url = _http_url(path if path.startswith('http') else f'{API_URL}{path}')
    if query:
        qs = urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        url = _http_url(f'{url}?{qs}')
    headers: dict[str, str] = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    data: bytes | None = None
    if file_field is not None:
        field, filename, content, content_type = file_field
        boundary = '----RbacLiveBoundary7ade'
        chunks = [
            f'--{boundary}\r\n'.encode(),
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode(),
            f'Content-Type: {content_type}\r\n\r\n'.encode(),
            content,
            b'\r\n',
        ]
        for key, value in (form or {}).items():
            chunks.extend([
                f'--{boundary}\r\n'.encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                str(value).encode(),
                b'\r\n',
            ])
        chunks.append(f'--{boundary}--\r\n'.encode())
        data = b''.join(chunks)
        headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
    elif json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False, default=str).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)  # ruff: ignore[suspicious-url-open-usage]
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # ruff: ignore[suspicious-url-open-usage]
            raw = resp.read()
            status = resp.status
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
        hdrs = {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])}
    body: Any
    try:
        body = json.loads(raw.decode() or 'null')
    except json.JSONDecodeError:
        body = raw.decode(errors='replace')
    return HttpResult(status=status, body=body, headers=hdrs, raw=raw)


def swagger_login(username: str, password: str) -> dict[str, Any]:
    res = _request(
        'POST',
        f'{SYS}/auth/login/swagger',
        query={'username': username, 'password': password},
    )
    if res.status >= 400:
        raise RuntimeError(f'登录失败 {username}: HTTP {res.status} {res.msg or res.body}')
    payload = res.body if isinstance(res.body, dict) else {}
    data = payload.get('data') if isinstance(payload.get('data'), dict) else payload
    token = data.get('access_token')
    if not token:
        raise RuntimeError(f'登录无 token {username}: {payload}')
    return data


def denied(res: HttpResult) -> bool:
    if res.status in {401, 403, 404}:
        return True
    return res.code in {401, 403, 404}


def no_business_body(res: HttpResult) -> bool:
    if denied(res):
        return True
    data = res.data
    if data in (None, {}, []):
        return True
    return bool(isinstance(data, dict) and not data.get('items') and int(data.get('total') or 0) == 0)


def assert_denied(res: HttpResult, *, label: str, allow_empty: bool = False) -> None:
    if denied(res):
        return
    if allow_empty and res.status < 400 and not res.items and res.total == 0:
        return
    raise AssertionError(f'{label} 期望拒绝/空，实际 HTTP {res.status} code={res.code} msg={res.msg} data={res.data!r}')


def assert_empty_list(res: HttpResult, *, label: str) -> None:
    if denied(res):
        return
    if res.status >= 400:
        raise AssertionError(f'{label} HTTP {res.status} {res.msg}')
    if res.items or res.total:
        raise AssertionError(f'{label} 期望空列表，total={res.total} items={res.items!r}')


def site_ids_of(items: list[dict[str, Any]]) -> set[int]:
    out: set[int] = set()
    for row in items:
        if row.get('site_id') is not None:
            out.add(int(row['site_id']))
    return out


@dataclass
class Actor:
    code: str
    username: str
    password: str
    token: str
    user_id: int | None = None

    def call(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        query: dict[str, Any] | None = None,
        form: dict[str, str] | None = None,
        file_field: tuple[str, str, bytes, str] | None = None,
    ) -> HttpResult:
        return _request(
            method,
            path,
            token=self.token,
            json_body=json_body,
            query=query,
            form=form,
            file_field=file_field,
        )


@dataclass
class RbacWorld:
    su: Actor
    sa: Actor
    ow_a: Actor
    dp_a: Actor
    ow_b: Actor
    empty: Actor
    rd_a: Actor
    rd_b: Actor
    site_a: dict[str, Any]
    site_b: dict[str, Any]
    rider_a: dict[str, Any]
    rider_b: dict[str, Any]
    order_a: dict[str, Any]
    order_b: dict[str, Any]
    period_a: dict[str, Any]
    period_b: dict[str, Any]
    payroll_a: dict[str, Any] | None
    payroll_b: dict[str, Any] | None
    adjustment_a: dict[str, Any]
    adjustment_b: dict[str, Any]
    advance_a: dict[str, Any] | None
    advance_b: dict[str, Any] | None
    batch_a: dict[str, Any] | None
    batch_b: dict[str, Any] | None
    plan_version: dict[str, Any] | None
    resigned_username: str
    notes: list[str] = field(default_factory=list)

    @property
    def site_a_id(self) -> int:
        return int(self.site_a['id'])

    @property
    def site_b_id(self) -> int:
        return int(self.site_b['id'])


def _actor_from_swagger(code: str, username: str, password: str, data: dict[str, Any]) -> Actor:
    user_obj = data.get('user') if isinstance(data.get('user'), dict) else {}
    uid = int(user_obj['id']) if user_obj.get('id') else None
    return Actor(code=code, username=username, password=password, token=data['access_token'], user_id=uid)


def _su_login() -> Actor:
    errors: list[str] = []
    for user, password in SU_USERS:
        result = _try_swagger_actor('SU', user, password)
        if isinstance(result, Actor):
            return result
        errors.append(str(result))
    raise RuntimeError(f'超管登录失败：{"; ".join(errors)}')


def _try_swagger_actor(code: str, username: str, password: str) -> Actor | Exception:
    try:
        return _actor_from_swagger(code, username, password, swagger_login(username, password))
    except Exception as exc:
        return exc


def _page(actor: Actor, path: str, query: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    q = {'page': 1, 'size': 50, **(query or {})}
    res = actor.call('GET', path, query=q)
    if res.status >= 400:
        raise RuntimeError(f'GET {path} 失败 {res.status} {res.msg}')
    return [row for row in res.items if isinstance(row, dict)]


def _find_user(su: Actor, username: str) -> dict[str, Any] | None:
    for row in _page(su, f'{SYS}/sys/users', {'username': username}):
        if row.get('username') == username:
            return row
    return None


def _ensure_user(su: Actor, username: str, *, role_id: int, nickname: str) -> dict[str, Any]:
    user = _find_user(su, username)
    if not user:
        res = su.call(
            'POST',
            f'{SYS}/sys/users',
            json_body={
                'username': username,
                'password': STAFF_PASS,
                'nickname': nickname,
                'email': None,
                'phone': None,
                'dept_id': 1,
                'roles': [role_id],
            },
        )
        if res.status >= 400:
            raise RuntimeError(f'创建用户 {username} 失败 {res.status} {res.msg}')
        user = res.data if isinstance(res.data, dict) else _find_user(su, username)
        if not user:
            raise RuntimeError(f'创建用户 {username} 后查不到')
    role_ids = []
    for role in user.get('roles') or []:
        if isinstance(role, dict):
            role_ids.append(int(role.get('id') or role.get('role_id') or 0))
        else:
            role_ids.append(int(role))
    if role_id not in role_ids:
        role_ids.append(role_id)
        su.call(
            'PUT',
            f'{SYS}/sys/users/{user["id"]}',
            json_body={
                'dept_id': user.get('dept_id') or 1,
                'username': user['username'],
                'nickname': user.get('nickname') or nickname,
                'avatar': user.get('avatar'),
                'email': user.get('email'),
                'phone': user.get('phone'),
                'roles': [rid for rid in role_ids if rid],
            },
        )
        user = _find_user(su, username) or user
    if not user.get('is_staff'):
        su.call('PUT', f'{SYS}/sys/users/{user["id"]}/permissions', query={'type': 'staff'})
    try:
        su.call('PUT', f'{SYS}/sys/users/{user["id"]}/password', json_body={'password': STAFF_PASS})
    except Exception:
        pass
    return user


def _ensure_site(su: Actor, code: str, name: str) -> dict[str, Any]:
    res = su.call('GET', f'{PREFIX}/sites/all')
    for row in res.items or (res.data or []):
        if isinstance(row, dict) and row.get('code') == code:
            return row
    created = su.call(
        'POST',
        f'{PREFIX}/sites',
        json_body={
            'code': code,
            'name': name,
            'settle_cycle': 'month',
            'status': 'enable',
            'advance_limit': 2000,
        },
    )
    if created.status >= 400:
        raise RuntimeError(f'创建站点 {code} 失败 {created.status} {created.msg}')
    res = su.call('GET', f'{PREFIX}/sites/all')
    for row in res.items or (res.data or []):
        if isinstance(row, dict) and row.get('code') == code:
            return row
    raise RuntimeError(f'站点 {code} 创建后不可见')


def _set_manager(su: Actor, site_id: int, user_id: int, role: str) -> None:
    current = su.call('GET', f'{PREFIX}/sites/{site_id}/managers')
    managers = []
    seen = False
    for row in current.data or []:
        if not isinstance(row, dict):
            continue
        uid = int(row['user_id'])
        if uid == user_id:
            managers.append({'user_id': uid, 'role': role})
            seen = True
        else:
            managers.append({'user_id': uid, 'role': row.get('role') or 'deputy'})
    if not seen:
        managers.append({'user_id': user_id, 'role': role})
    res = su.call('PUT', f'{PREFIX}/sites/{site_id}/managers', json_body=managers)
    if res.status >= 400:
        raise RuntimeError(f'配置负责人失败 site={site_id}: {res.status} {res.msg}')


def _find_rider(su: Actor, site_id: int, job_no: str) -> dict[str, Any] | None:
    for row in _page(su, f'{PREFIX}/riders', {'site_id': site_id, 'keyword': job_no}):
        if row.get('job_no') == job_no:
            return row
    return None


def _ensure_rider(su: Actor, site_id: int, job_no: str, name: str) -> dict[str, Any]:
    rider = _find_rider(su, site_id, job_no)
    if rider:
        return rider
    res = su.call(
        'POST',
        f'{PREFIX}/riders',
        json_body={
            'job_no': job_no,
            'name': name,
            'phone': None,
            'site_id': site_id,
            'employ_type': 'part_time',
            'hire_date': '2026-07-01',
            'leave_date': None,
            'status': 'on_job',
            'advance_limit': 800,
            'settle_cycle_override': None,
            'cycle_config_override': None,
            'remark': 'RBAC 夹具骑手',
        },
    )
    if res.status >= 400:
        raise RuntimeError(f'创建骑手 {job_no} 失败 {res.status} {res.msg}')
    rider = _find_rider(su, site_id, job_no)
    if not rider:
        raise RuntimeError(f'骑手 {job_no} 创建后查不到')
    return rider


def _open_account(su: Actor, rider: dict[str, Any], username: str) -> None:
    if rider.get('user_id'):
        return
    res = su.call(
        'POST',
        f'{PREFIX}/riders/{rider["id"]}/open-account',
        json_body={'password': STAFF_PASS, 'reason': 'RBAC 夹具开通'},
    )
    if res.status >= 400:
        raise RuntimeError(f'开通账号 {username} 失败 {res.status} {res.msg}')


def _ensure_order(su: Actor, site_id: int, rider_id: int, order_no: str) -> dict[str, Any]:
    for row in _page(su, f'{PREFIX}/orders', {'site_id': site_id, 'order_no': order_no}):
        if row.get('order_no') == order_no:
            return row
    res = su.call(
        'POST',
        f'{PREFIX}/orders',
        json_body={
            'order_no': order_no,
            'site_id': site_id,
            'rider_id': rider_id,
            'distance_km': '2.50',
            'weight_jin': '3.00',
            'order_time': '2026-07-15T12:00:00+08:00',
            'deliver_time': '2026-07-15T12:30:00+08:00',
            'status': 'completed',
            'amount': '18.00',
            'remark': 'RBAC 夹具订单',
        },
    )
    if res.status >= 400:
        raise RuntimeError(f'补录订单 {order_no} 失败 {res.status} {res.msg}')
    data = res.data if isinstance(res.data, dict) else None
    if data and data.get('id'):
        return data
    for row in _page(su, f'{PREFIX}/orders', {'site_id': site_id, 'order_no': order_no}):
        if row.get('order_no') == order_no:
            return row
    raise RuntimeError(f'订单 {order_no} 创建后查不到')


def _ensure_adjustment(su: Actor, rider_id: int, remark: str) -> dict[str, Any]:
    subjects = su.call('GET', f'{PREFIX}/subjects/all')
    rows = subjects.data if isinstance(subjects.data, list) else subjects.items
    subject = next((row for row in rows if isinstance(row, dict) and row.get('code') == 'COMPLAINT'), None)
    if not subject:
        raise RuntimeError('无科目 COMPLAINT')
    for row in _page(su, f'{PREFIX}/adjustments', {'rider_id': rider_id}):
        if row.get('remark') == remark:
            return row
    res = su.call(
        'POST',
        f'{PREFIX}/adjustments',
        json_body={
            'rider_id': rider_id,
            'biz_date': '2026-07-15',
            'subject_id': subject['id'],
            'amount': '10.00',
            'remark': remark,
        },
    )
    if res.status >= 400:
        raise RuntimeError(f'录入奖惩失败 {res.status} {res.msg}')
    if isinstance(res.data, dict) and res.data.get('id'):
        return res.data
    for row in _page(su, f'{PREFIX}/adjustments', {'rider_id': rider_id}):
        if row.get('remark') == remark:
            return row
    raise RuntimeError('奖惩创建后查不到')


def _ensure_period(su: Actor, site_id: int) -> dict[str, Any]:
    month = '2026-07'
    for row in _page(su, f'{PREFIX}/periods', {'site_id': site_id, 'month': month}):
        if int(row.get('rider_id') or 0) == 0:
            return row
    res = su.call('POST', f'{PREFIX}/periods/generate', json_body={'site_id': site_id, 'month': month})
    if res.status >= 400:
        raise RuntimeError(f'生成周期失败 site={site_id} {res.status} {res.msg}')
    for row in _page(su, f'{PREFIX}/periods', {'site_id': site_id, 'month': month}):
        if int(row.get('rider_id') or 0) == 0:
            return row
    data = res.data
    if isinstance(data, dict) and data.get('id'):
        return data
    items = data.get('items') if isinstance(data, dict) else None
    if items:
        return items[0]
    raise RuntimeError(f'站点 {site_id} 无 2026-07 周期')


def _maybe_calculate(su: Actor, period: dict[str, Any], notes: list[str]) -> dict[str, Any] | None:
    if period.get('status') in {'locked', 'paid'}:
        detail = su.call('GET', f'{PREFIX}/periods/{period["id"]}')
        payrolls = (detail.data or {}).get('payrolls') if isinstance(detail.data, dict) else []
        return payrolls[0] if payrolls else None
    res = su.call('POST', f'{PREFIX}/periods/{period["id"]}/calculate', json_body={'rider_ids': None})
    if res.status >= 400:
        notes.append(f'算薪 period={period["id"]} HTTP {res.status} {res.msg}')
    detail = su.call('GET', f'{PREFIX}/periods/{period["id"]}')
    payrolls = []
    if isinstance(detail.data, dict):
        payrolls = detail.data.get('payrolls') or []
    return payrolls[0] if payrolls else None


def _build_import_xlsx(site_code: str, job_no: str, order_no: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append([
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
    ws.append([
        site_code,
        job_no,
        order_no,
        1.2,
        2.0,
        '2026-07-16 10:00:00',
        '2026-07-16 10:20:00',
        'completed',
        12,
        'RBAC导入',
    ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _ensure_batch(su: Actor, site: dict[str, Any], rider: dict[str, Any], notes: list[str]) -> dict[str, Any] | None:
    existing = _page(su, f'{PREFIX}/import-batches', {'site_id': site['id']})
    if existing:
        return existing[0]
    content = _build_import_xlsx(site['code'], rider['job_no'], f'RBACIMP-{site["code"]}-1')
    res = su.call(
        'POST',
        f'{PREFIX}/orders/import',
        form={'site_id': str(site['id']), 'skip_errors': 'true', 'auto_recalc': 'false'},
        file_field=('file', 'rbac.xlsx', content, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
    )
    if res.status >= 400:
        notes.append(f'导入失败 site={site["id"]} {res.status} {res.msg}')
        return None
    existing = _page(su, f'{PREFIX}/import-batches', {'site_id': site['id']})
    return existing[0] if existing else None


def _ensure_advance(rider_actor: Actor, notes: list[str], tag: str) -> dict[str, Any] | None:
    listed = rider_actor.call('GET', f'{PREFIX}/me/advances')
    for row in listed.items or (listed.data or []):
        if isinstance(row, dict) and row.get('status') == 'pending' and tag in str(row.get('reason') or ''):
            return row
    res = rider_actor.call(
        'POST',
        f'{PREFIX}/me/advances',
        json_body={'amount': '20.00', 'reason': f'{tag} 权限夹具预支'},
    )
    if res.status >= 400:
        notes.append(f'预支申请失败 {rider_actor.username}: {res.status} {res.msg}')
        return None
    return res.data if isinstance(res.data, dict) else None


def _actor_from_user(code: str, username: str, user: dict[str, Any]) -> Actor:
    data = swagger_login(username, STAFF_PASS)
    return Actor(code=code, username=username, password=STAFF_PASS, token=data['access_token'], user_id=int(user['id']))


def bootstrap_world() -> RbacWorld:
    notes: list[str] = []
    su = _su_login()
    site_a = _ensure_site(su, 'RBACA', '权限站A')
    site_b = _ensure_site(su, 'RBACB', '权限站B')

    sa_user = _ensure_user(su, 'salary_admin', role_id=92001, nickname='薪资管理员夹具')
    ow_a_user = _ensure_user(
        su, os.environ.get('RIDER_SALARY_OW_A', 'rbac_owner_a'), role_id=92002, nickname='站点A负责人'
    )
    dp_user = _ensure_user(su, 'site_deputy_a', role_id=92003, nickname='站点A副负责人')
    ow_b_user = _ensure_user(su, 'site_owner_b', role_id=92002, nickname='站点B负责人')
    empty_user = _ensure_user(su, 'site_empty_owner', role_id=92002, nickname='无站点负责人')

    _set_manager(su, int(site_a['id']), int(ow_a_user['id']), 'owner')
    _set_manager(su, int(site_a['id']), int(dp_user['id']), 'deputy')
    _set_manager(su, int(site_b['id']), int(ow_b_user['id']), 'owner')

    rider_a = _ensure_rider(su, int(site_a['id']), 'RBAC-RA', '权限骑手A')
    rider_b = _ensure_rider(su, int(site_b['id']), 'RBAC-RB', '权限骑手B')
    resigned = _ensure_rider(su, int(site_a['id']), 'RBAC-RX', '权限离职骑手')
    _open_account(su, rider_a, 'RBAC-RA')
    _open_account(su, rider_b, 'RBAC-RB')
    _open_account(su, resigned, 'RBAC-RX')
    rider_a = _find_rider(su, int(site_a['id']), 'RBAC-RA') or rider_a
    rider_b = _find_rider(su, int(site_b['id']), 'RBAC-RB') or rider_b
    resigned = _find_rider(su, int(site_a['id']), 'RBAC-RX') or resigned
    if resigned.get('status') != 'resigned':
        leave = su.call(
            'PUT',
            f'{PREFIX}/riders/{resigned["id"]}/leave',
            json_body={'leave_date': '2026-07-20', 'reason': 'RBAC 离职夹具'},
        )
        if leave.status >= 400:
            notes.append(f'离职夹具失败 {leave.status} {leave.msg}')

    versions = su.call('GET', f'{PREFIX}/plan-versions/active')
    version_list = versions.data if isinstance(versions.data, list) else versions.items
    plan_version = version_list[0] if version_list else None
    if plan_version and not any(
        row.get('plan_version_id') == plan_version['id']
        for row in (su.call('GET', f'{PREFIX}/riders/{rider_a["id"]}/bindings').data or [])
        if isinstance(row, dict)
    ):
        bind = su.call(
            'POST',
            f'{PREFIX}/riders/{rider_a["id"]}/bindings',
            json_body={
                'plan_version_id': plan_version['id'],
                'binding_type': 'default',
                'start_date': '2026-07-01',
                'end_date': None,
                'reason': 'RBAC 绑定',
            },
        )
        if bind.status >= 400:
            notes.append(f'绑方案失败 {bind.status} {bind.msg}')

    order_a = _ensure_order(su, int(site_a['id']), int(rider_a['id']), 'RBAC-OA-001')
    order_b = _ensure_order(su, int(site_b['id']), int(rider_b['id']), 'RBAC-OB-001')
    adj_a = _ensure_adjustment(su, int(rider_a['id']), 'RBAC-ADJ-A')
    adj_b = _ensure_adjustment(su, int(rider_b['id']), 'RBAC-ADJ-B')
    period_a = _ensure_period(su, int(site_a['id']))
    period_b = _ensure_period(su, int(site_b['id']))
    payroll_a = _maybe_calculate(su, period_a, notes)
    payroll_b = _maybe_calculate(su, period_b, notes)
    batch_a = _ensure_batch(su, site_a, rider_a, notes)
    batch_b = _ensure_batch(su, site_b, rider_b, notes)

    sa = _actor_from_user('SA', 'salary_admin', sa_user)
    ow_a = _actor_from_user('OW-A', ow_a_user['username'], ow_a_user)
    dp_a = _actor_from_user('DP-A', 'site_deputy_a', dp_user)
    ow_b = _actor_from_user('OW-B', 'site_owner_b', ow_b_user)
    empty = _actor_from_user('EMPTY', 'site_empty_owner', empty_user)

    # 骑手工号即用户名（open-account 约定）
    rd_a_data = swagger_login(rider_a['job_no'], STAFF_PASS)
    rd_b_data = swagger_login(rider_b['job_no'], STAFF_PASS)
    rd_a = Actor(code='RD-A', username=rider_a['job_no'], password=STAFF_PASS, token=rd_a_data['access_token'])
    rd_b = Actor(code='RD-B', username=rider_b['job_no'], password=STAFF_PASS, token=rd_b_data['access_token'])

    advance_a = _ensure_advance(rd_a, notes, 'RA')
    advance_b = _ensure_advance(rd_b, notes, 'RB')

    return RbacWorld(
        su=su,
        sa=sa,
        ow_a=ow_a,
        dp_a=dp_a,
        ow_b=ow_b,
        empty=empty,
        rd_a=rd_a,
        rd_b=rd_b,
        site_a=site_a,
        site_b=site_b,
        rider_a=rider_a,
        rider_b=rider_b,
        order_a=order_a,
        order_b=order_b,
        period_a=period_a,
        period_b=period_b,
        payroll_a=payroll_a,
        payroll_b=payroll_b,
        adjustment_a=adj_a,
        adjustment_b=adj_b,
        advance_a=advance_a,
        advance_b=advance_b,
        batch_a=batch_a,
        batch_b=batch_b,
        plan_version=plan_version,
        resigned_username=resigned['job_no'],
        notes=notes,
    )

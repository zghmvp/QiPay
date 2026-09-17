/**
 * 权限饱和夹具：两站 + SA/副负责人/站 B 负责人/空负责人 + 骑手账号。
 * 与 pytest rbac_live.bootstrap_world 使用同一批用户名。
 */
import { fileURLToPath } from 'node:url';

const API_URL = process.env.API_URL || 'http://127.0.0.1:8000';
const ADMIN_USER = process.env.CDP_USER || 'admin';
const ADMIN_PASS = process.env.CDP_PASS || '123456';
const STAFF_PASS = process.env.CDP_SITE_OWNER_PASS || 'Rider@123456';

async function swaggerLogin(username, password) {
  const res = await fetch(
    `${API_URL}/api/v1/auth/login/swagger?username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
    { method: 'POST' },
  );
  if (!res.ok) throw new Error(`login ${username} ${res.status}`);
  return res.json();
}

function headers(token) {
  return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
}

async function api(token, method, urlPath, body) {
  const res = await fetch(`${API_URL}${urlPath}`, {
    method,
    headers: headers(token),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`${method} ${urlPath} → ${res.status}: ${json.msg || res.statusText}`);
  return json;
}

async function findUser(token, username) {
  const qs = new URLSearchParams({ page: '1', size: '20', username });
  const page = await api(token, 'GET', `/api/v1/sys/users?${qs}`);
  return (page?.data?.items || []).find((u) => u.username === username) || null;
}

async function ensureUser(token, username, roleId, nickname) {
  let user = await findUser(token, username);
  if (!user) {
    const created = await api(token, 'POST', '/api/v1/sys/users', {
      username,
      password: STAFF_PASS,
      nickname,
      email: null,
      phone: null,
      dept_id: 1,
      roles: [roleId],
    });
    user = created?.data || (await findUser(token, username));
  }
  if (!user?.is_staff) {
    await api(token, 'PUT', `/api/v1/sys/users/${user.id}/permissions?type=staff`);
  }
  try {
    await api(token, 'PUT', `/api/v1/sys/users/${user.id}/password`, { password: STAFF_PASS });
  } catch {
    /* ignore */
  }
  console.log('user', username, user.id);
  return user;
}

async function ensureSite(token, code, name) {
  const all = await api(token, 'GET', '/api/v1/rider-salary/sites/all');
  const hit = (all?.data || []).find((s) => s.code === code);
  if (hit) return hit;
  await api(token, 'POST', '/api/v1/rider-salary/sites', {
    code,
    name,
    settle_cycle: 'month',
    status: 'enable',
    advance_limit: 2000,
  });
  const again = await api(token, 'GET', '/api/v1/rider-salary/sites/all');
  return (again?.data || []).find((s) => s.code === code);
}

async function setManager(token, siteId, userId, role) {
  const cur = await api(token, 'GET', `/api/v1/rider-salary/sites/${siteId}/managers`);
  const managers = (cur?.data || []).map((m) => ({ user_id: m.user_id, role: m.role }));
  if (!managers.some((m) => m.user_id === userId)) {
    managers.push({ user_id: userId, role });
    await api(token, 'PUT', `/api/v1/rider-salary/sites/${siteId}/managers`, managers);
  }
}

async function main() {
  let login;
  try {
    login = await swaggerLogin(ADMIN_USER, ADMIN_PASS);
  } catch {
    login = await swaggerLogin('admin', 'admin');
  }
  const token = login.access_token || login.data?.access_token;
  const siteA = await ensureSite(token, 'RBACA', '权限站A');
  const siteB = await ensureSite(token, 'RBACB', '权限站B');
  const sa = await ensureUser(token, 'salary_admin', 92001, '薪资管理员夹具');
  const owA = await ensureUser(token, process.env.CDP_RBAC_OWNER || 'rbac_owner_a', 92002, '站点A负责人');
  const dp = await ensureUser(token, 'site_deputy_a', 92003, '站点A副负责人');
  const owB = await ensureUser(token, 'site_owner_b', 92002, '站点B负责人');
  await ensureUser(token, 'site_empty_owner', 92002, '无站点负责人');
  await setManager(token, siteA.id, owA.id, 'owner');
  await setManager(token, siteA.id, dp.id, 'deputy');
  await setManager(token, siteB.id, owB.id, 'owner');
  console.log('RBAC fixtures ready', { siteA: siteA.id, siteB: siteB.id, sa: sa.id });
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}

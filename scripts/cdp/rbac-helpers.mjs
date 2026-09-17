/**
 * 权限饱和 CDP 共用：登录、侧栏、同 token 打 API。
 * 不 import harness.mjs，避免与 specs 循环依赖。
 */
export const CONFIG = {
  apiUrl: process.env.API_URL || 'http://127.0.0.1:8000',
  adminUrl: process.env.ADMIN_URL || 'http://127.0.0.1:5173',
  accessKey: process.env.FBA_ACCESS_KEY || 'fba-ui-5.7.0-dev-core-access',
};

export const RBAC = {
  ownerUser: process.env.CDP_RBAC_OWNER || 'rbac_owner_a',
  ownerPass: process.env.CDP_RBAC_OWNER_PASS || process.env.CDP_SITE_OWNER_PASS || 'Rider@123456',
  saUser: process.env.CDP_SA_USER || 'salary_admin',
  saPass: process.env.CDP_SA_PASS || process.env.CDP_SITE_OWNER_PASS || 'Rider@123456',
  deputyUser: process.env.CDP_DEPUTY_USER || 'site_deputy_a',
  deputyPass: process.env.CDP_DEPUTY_PASS || process.env.CDP_SITE_OWNER_PASS || 'Rider@123456',
  riderUser: process.env.CDP_RIDER_USER || 'RBAC-RB',
  riderPass: process.env.CDP_RIDER_PASS || process.env.CDP_SITE_OWNER_PASS || 'Rider@123456',
  h5Url: process.env.H5_URL || 'http://127.0.0.1:5174',
  siteACode: process.env.CDP_SITE_A_CODE || 'RBACA',
  siteBCode: process.env.CDP_SITE_B_CODE || 'RBACB',
};

export function unwrapLogin(payload) {
  const nested = payload?.data && typeof payload.data === 'object' ? payload.data : null;
  const data = nested?.access_token ? nested : payload;
  if (!data?.access_token) {
    throw new Error(`login payload missing access_token: ${JSON.stringify(payload).slice(0, 240)}`);
  }
  return { ...data, access_token: data.access_token, user: data.user || payload.user };
}

export async function loginAs(username, password, apiUrl = CONFIG.apiUrl) {
  const res = await fetch(
    `${apiUrl}/api/v1/auth/login/swagger?username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
    { method: 'POST' },
  );
  if (!res.ok) throw new Error(`login failed ${username}: ${res.status}`);
  return unwrapLogin(await res.json());
}

export function isDenied(res) {
  const code = res?.json?.code;
  return [401, 403, 404].includes(res?.status) || [401, 403, 404].includes(code);
}

export async function injectAdmin(page, token, sessionUuid = null) {
  await page.goto(`${CONFIG.adminUrl}/auth/login`, { waitUntil: 'domcontentloaded' });
  await page.evaluate(
    ({ key, token, sessionUuid }) => {
      const raw = localStorage.getItem(key);
      const base = raw ? JSON.parse(raw) : {};
      localStorage.setItem(
        key,
        JSON.stringify({
          ...base,
          accessToken: token,
          accessSessionUuid: sessionUuid,
          refreshToken: null,
          isLockScreen: false,
        }),
      );
    },
    { key: CONFIG.accessKey, token, sessionUuid },
  );
}

export async function api(token, method, urlPath, body) {
  const res = await fetch(`${CONFIG.apiUrl}${urlPath}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = { raw: text };
  }
  return { status: res.status, json, msg: json?.msg || '' };
}

export async function injectAndOpen(page, token, sessionUuid, path = '/analytics') {
  await injectAdmin(page, token, sessionUuid);
  await page.goto(`${CONFIG.adminUrl}${path}`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
}

export async function sidebarText(page) {
  const nav = page.locator('aside, .vben-layout-sidebar, [class*="sidebar"]').first();
  try {
    await nav.waitFor({ state: 'visible', timeout: 8000 });
    return ((await nav.innerText()) || '').trim();
  } catch {
    return ((await page.locator('body').innerText()) || '').trim();
  }
}

export function assertHas(text, labels, who) {
  for (const label of labels) {
    if (!text.includes(label)) {
      throw new Error(`${who} 侧栏缺少「${label}」`);
    }
  }
}

export function assertHasNone(text, labels, who) {
  for (const label of labels) {
    if (text.includes(label)) {
      throw new Error(`${who} 侧栏不应出现「${label}」`);
    }
  }
}

export const OWNER_MENUS = ['工作台', '骑手管理', '订单明细', '结算周期', '薪资日历', '预支审核', '操作日志'];
export const OWNER_FORBIDDEN = ['站点管理'];
export const SA_MENUS = ['站点管理', '薪资方案', '工作台'];

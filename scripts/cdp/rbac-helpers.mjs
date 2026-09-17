/**
 * 权限饱和 CDP 共用：登录、侧栏、同 token 打 API。
 * 不 import harness.mjs，避免与 specs 循环依赖。
 */
export const CONFIG = {
  apiUrl: process.env.API_URL || 'http://127.0.0.1:8000',
  adminUrl: process.env.ADMIN_URL || 'http://127.0.0.1:5173',
  accessKey: process.env.FBA_ACCESS_KEY || 'undefined-5.7.0-dev-core-access',
  accessKeyAliases: (process.env.FBA_ACCESS_KEY_ALIASES || 'fba-ui-5.7.0-dev-core-access')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean),
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
  let session = data.session_uuid || nested?.session_uuid || null;
  if (!session && data.access_token) {
    try {
      const mid = data.access_token.split('.')[1];
      const json = JSON.parse(Buffer.from(mid.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString());
      session = json.session_uuid || null;
    } catch {
      /* ignore */
    }
  }
  return {
    ...data,
    access_token: data.access_token,
    session_uuid: session,
    user: data.user || payload.user || nested?.user,
  };
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
  const keys = [CONFIG.accessKey, ...(CONFIG.accessKeyAliases || [])];
  await page.evaluate(
    ({ keys, token, sessionUuid }) => {
      // 清掉上一角色残留，再写入当前 token
      localStorage.clear();
      const payload = {
        accessToken: token,
        accessSessionUuid: sessionUuid,
        refreshToken: null,
        accessCodes: [],
        isLockScreen: false,
      };
      for (const key of keys) {
        localStorage.setItem(key, JSON.stringify(payload));
      }
    },
    { keys, token, sessionUuid },
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
  const menuWait = page
    .waitForResponse(
      (r) => r.url().includes('/sys/menus/sidebar') && r.status() === 200,
      { timeout: 25000 },
    )
    .catch(() => null);
  await page.goto(`${CONFIG.adminUrl}${path}`, {
    waitUntil: 'domcontentloaded',
    timeout: 60000,
  });
  await menuWait;
  try {
    await page.waitForFunction(
      () => {
        const t = document.body?.textContent || '';
        if (t.includes('登录') && t.includes('请输入您的账户')) return true;
        return t.includes('站点管理') || t.includes('订单明细') || t.includes('骑手管理') || t.includes('结算周期');
      },
      { timeout: 25000 },
    );
  } catch {
    /* continue; assertions will fail clearly */
  }
  await page.waitForTimeout(500);
}

export async function sidebarText(page) {
  // 折叠侧栏：菜单名在 DOM 中但 aside.innerText 为空；勿用「aside || body」短路掉 body
  return await page.evaluate(() => {
    const aside = document.querySelector('aside')?.textContent || '';
    const body = document.body?.textContent || '';
    return `${aside}\n${body}`.replace(/\s+/g, '\n');
  });
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

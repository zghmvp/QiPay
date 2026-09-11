import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const { chromium } = createRequire(
  '/Users/zghmvp/Desktop/QiPay/fastapi-best-architecture-ui/package.json',
)('playwright');

const OUT = '/Users/zghmvp/Desktop/QiPay/docs/验收截图/ux';
const API = 'http://127.0.0.1:8000';
const ADMIN = 'http://localhost:5173';
const ACCESS_KEY = 'fba-ui-5.7.0-dev-core-access';

async function swaggerLogin(username, password) {
  const res = await fetch(
    `${API}/api/v1/auth/login/swagger?username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
    { method: 'POST' },
  );
  if (!res.ok) throw new Error(`login failed ${username}: ${res.status}`);
  return res.json();
}

async function injectAdmin(page, token, sessionUuid = null) {
  await page.goto(`${ADMIN}/auth/login`, { waitUntil: 'domcontentloaded' });
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
    { key: ACCESS_KEY, token, sessionUuid },
  );
}

async function shot(page, name) {
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file });
  console.log('OK', file);
}

async function openPage(page, url) {
  await page.goto(`${ADMIN}${url}`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  await page.waitForTimeout(800);
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const admin = await swaggerLogin('admin', '123456');

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await ctx.newPage();

  await injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);

  const routes = [
    ['01-工作台', '/rider-salary/dashboard?site_id=1&month=2026-09'],
    ['02-站点列表', '/rider-salary/site'],
    ['03-订单列表', '/rider-salary/order'],
    ['04-结算周期', '/rider-salary/period'],
    ['05-日历', '/rider-salary/calendar?site_id=1&rider_id=1&month=2026-09'],
    ['06-方案管理', '/rider-salary/plan'],
    ['07-骑手列表', '/rider-salary/rider'],
  ];

  for (const [name, route] of routes) {
    await openPage(page, route);
    await shot(page, name);
  }

  await page.setViewportSize({ width: 1280, height: 720 });
  await page.waitForTimeout(500);
  await shot(page, '08-骑手列表-resize-1280');
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(500);
  await shot(page, '09-骑手列表-resize-1440');

  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const OUT = '/Users/zghmvp/Desktop/QiPay/docs/验收截图';
const API = 'http://127.0.0.1:8000';
const ADMIN = 'http://localhost:5173';
const H5 = 'http://localhost:5174';
const ACCESS_KEY = 'fba-ui-5.7.0-dev-core-access';

async function swaggerLogin(username, password) {
  const res = await fetch(
    `${API}/api/v1/auth/login/swagger?username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
    { method: 'POST' },
  );
  if (!res.ok) throw new Error(`login failed ${username}: ${res.status}`);
  return res.json();
}

async function shot(page, name) {
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  console.log('OK', file);
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

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const admin = await swaggerLogin('admin', '123456');
  const rider = await swaggerLogin('D5A001', 'Rider@123456');

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  await injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  await page.goto(`${ADMIN}/rider-salary/dashboard?site_id=1&month=2026-09`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  await shot(page, 'A1-工作台');

  await page.goto(`${ADMIN}/rider-salary/calendar?site_id=1&rider_id=1&month=2026-09`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  await shot(page, 'A2-日历色带');

  await page.goto(`${ADMIN}/rider-salary/period?id=1`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  await shot(page, 'A3-周期详情');

  await page.goto(`${ADMIN}/rider-salary/order`, { waitUntil: 'networkidle', timeout: 60000 });
  await shot(page, 'A4-订单页');

  await page.goto(`${ADMIN}/rider-salary/period`, { waitUntil: 'networkidle', timeout: 60000 });
  await shot(page, 'A5-结算周期');

  await page.goto(`${ADMIN}/rider-salary/advance`, { waitUntil: 'networkidle', timeout: 60000 });
  await shot(page, 'A6-预支审核');

  await page.goto(`${ADMIN}/rider-salary/plan`, { waitUntil: 'networkidle', timeout: 60000 });
  await shot(page, 'A7-方案管理');

  const h5 = await ctx.newPage();
  await h5.goto(`${H5}/login`, { waitUntil: 'domcontentloaded' });
  await h5.evaluate(
    ({ token }) => localStorage.setItem('rider_h5_token', token),
    { token: rider.access_token },
  );

  const h5Routes = [
    ['B1-首页', '/home'],
    ['B2-日详情', '/day/2026-09-10'],
    ['B3-当前方案', '/plan'],
    ['B4-奖惩明细', '/adjustments'],
    ['B5-预支', '/advance'],
    ['B6-公告', '/notices'],
  ];
  for (const [name, route] of h5Routes) {
    await h5.goto(`${H5}${route}`, { waitUntil: 'networkidle', timeout: 60000 });
    await shot(h5, name);
  }

  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

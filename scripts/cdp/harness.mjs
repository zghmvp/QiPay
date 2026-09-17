/**
 * CDP harness：Playwright connectOverCDP + 鉴权注入。
 * 默认连接本机调试 Chrome（9222），禁止写死本机 Desktop 绝对路径。
 *
 * 用法：
 *   CDP_URL=http://127.0.0.1:9222 ADMIN_URL=http://127.0.0.1:5173 API_URL=http://127.0.0.1:8000 \
 *     node scripts/cdp/harness.mjs [spec-name]
 *
 * 不传 spec-name 时列出可用场景。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { chromium } from 'playwright';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '../..');

export const CONFIG = {
  cdpUrl: process.env.CDP_URL || 'http://127.0.0.1:9222',
  apiUrl: process.env.API_URL || 'http://127.0.0.1:8000',
  adminUrl: process.env.ADMIN_URL || 'http://127.0.0.1:5173',
  accessKey: process.env.FBA_ACCESS_KEY || 'fba-ui-5.7.0-dev-core-access',
  mediaDir:
    process.env.CDP_MEDIA_DIR ||
    path.join(
      process.env.CURSOR_AGENT_STORE ||
        '/cursor/stores/bc-2955b371-f65c-4990-a229-d877e2ac6c7a',
      'media',
    ),
  username: process.env.CDP_USER || 'admin',
  password: process.env.CDP_PASS || '123456',
  siteOwnerUser: process.env.CDP_SITE_OWNER || 'site_owner_d2',
  siteOwnerPass: process.env.CDP_SITE_OWNER_PASS || 'Rider@123456',
};

export async function swaggerLogin(username, password, apiUrl = CONFIG.apiUrl) {
  const res = await fetch(
    `${apiUrl}/api/v1/auth/login/swagger?username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
    { method: 'POST' },
  );
  if (!res.ok) {
    throw new Error(`login failed ${username}: ${res.status}`);
  }
  return res.json();
}

export async function injectAdmin(page, token, sessionUuid = null) {
  await page.goto(`${CONFIG.adminUrl}/auth/login`, {
    waitUntil: 'domcontentloaded',
  });
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

export async function shot(page, name) {
  fs.mkdirSync(CONFIG.mediaDir, { recursive: true });
  const file = path.join(CONFIG.mediaDir, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  console.log('SHOT', file);
  return file;
}

export async function connectBrowser() {
  const browser = await chromium.connectOverCDP(CONFIG.cdpUrl);
  const context =
    browser.contexts()[0] || (await browser.newContext({ viewport: { width: 1440, height: 900 } }));
  const page = context.pages()[0] || (await context.newPage());
  return { browser, context, page };
}

export function assertNoPaymentTaxCopy(text) {
  const banned = ['提现', '个税', '社保', '代发工资', '银行打款'];
  for (const word of banned) {
    if (text.includes(word)) {
      throw new Error(`禁止出现支付/税务文案：${word}`);
    }
  }
}

export async function assertChineseOrAmount(page, selectors) {
  for (const sel of selectors) {
    const el = page.locator(sel).first();
    await el.waitFor({ state: 'visible', timeout: 30000 });
    const text = ((await el.innerText()) || '').trim();
    if (!text) throw new Error(`空文案：${sel}`);
    const hasZh = /[\u4e00-\u9fff]/.test(text);
    const hasNum = /\d/.test(text);
    if (!hasZh && !hasNum) {
      throw new Error(`需中文或金额数字：${sel} => ${text}`);
    }
  }
}

async function loadSpecs() {
  const specsDir = path.join(__dirname, 'specs');
  const files = fs
    .readdirSync(specsDir)
    .filter((f) => f.endsWith('.spec.mjs'))
    .sort();
  const map = new Map();
  for (const file of files) {
    const mod = await import(pathToFileURL(path.join(specsDir, file)).href);
    const name = mod.name || file.replace(/\.spec\.mjs$/, '');
    map.set(name, mod);
  }
  return map;
}

async function main() {
  const specs = await loadSpecs();
  const wanted = process.argv[2];
  if (!wanted) {
    console.log('可用 CDP 场景：');
    for (const name of specs.keys()) console.log(' -', name);
    console.log('\n运行：node scripts/cdp/harness.mjs <scene>');
    process.exit(0);
  }
  const mod = specs.get(wanted);
  if (!mod || typeof mod.run !== 'function') {
    throw new Error(`未知场景：${wanted}`);
  }
  const { browser, page } = await connectBrowser();
  try {
    await mod.run({ page, browser, config: CONFIG, helpers: {
      swaggerLogin,
      injectAdmin,
      shot,
      assertNoPaymentTaxCopy,
      assertChineseOrAmount,
    }});
    console.log('PASS', wanted);
  } finally {
    // 不关闭用户调试 Chrome；仅断开 CDP
    await browser.close().catch(() => {});
  }
}

const isDirect =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isDirect) {
  main().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}

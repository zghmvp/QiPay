/**
 * CDP harness：Playwright connectOverCDP + 鉴权注入。
 * 默认连接本机调试 Chrome（9222），禁止写死本机 Desktop 绝对路径。
 *
 * 用法：
 *   CDP_URL=http://127.0.0.1:9222 ADMIN_URL=http://127.0.0.1:5173 API_URL=http://127.0.0.1:8000 \
 *     node scripts/cdp/harness.mjs [spec-name]
 *
 * 灌种（FIX_C17_R1 + site_owner_d2 + stale + FIX_C17_LOCK 无 stale 硬失败周期）：
 *   API_URL=http://127.0.0.1:8000 CDP_USER=admin CDP_PASS=admin \
 *     node scripts/cdp/seed-xiaoxiang-fixtures.mjs
 *
 * 推荐环境（福民演示机）：
 *   CDP_PASS=admin CDP_SITE_ID=<福民> CDP_RIDER_ID=<FIX_C17_R1_id> CDP_MONTH=2026-09
 *   CDP_SITE_OWNER=site_owner_d2 CDP_SITE_OWNER_PASS=Rider@123456
 *   CDP_LOCK_HARD_FAIL_PERIOD_ID=<FIX_C17_LOCK 骑手级周期，可选>
 *   （勿把正式 Must #5 改成 CDP_SITE_OWNER=admin）
 *
 * Cycle 1 具名：ops-calendar-adjust-date-window / ops-import-not-payroll /
 *   ops-order-missing-delivery-filter / ops-lock-reason-matches-calc /
 *   ops-payroll-list-period-picker / cdp-admin-subject-filter-name
 * Cycle 2 具名：trial-case-gold / ops-plan-guarantee-last /
 *   ops-export-attention-parity / cdp-admin-payslip-layers /
 *   cdp-admin-deduction-remark / cdp-admin-calc-success-four-numbers /
 *   ops-rider-profile-to-payroll / ops-queued-calc-progress
 * Cycle 3 具名：ops-calc-success-vs-existing / ops-export-adjustment-sheet /
 *   trial-equals-calc / ops-plan-threshold-xor / ops-calc-rider-picker-not-truncated
 * Cycle 4 具名：ops-dashboard-insight-card-scope / ops-calendar-month-export-confirm /
 *   ops-dashboard-abnormal-attention-landing / ops-dashboard-lock-overdue-visible /
 *   ops-plan-activate-not-full-trial（挂 trial-equals-calc 加一步，不新造 XOR/金标 Must 名）
 * Cycle 5 具名：cdp-admin-payslip-hide-empty-days / ops-dashboard-no-plan-to-binding /
 *   ops-plan-manual-not-double（挂现有方案保存 spec，不新造 XOR/金标/启用闸 Must 名）
 * 钩子对齐 #19+#24+#27：period-export-* / period-export-adj-* /
 *   period-export-period-row / calendar-export-month /
 *   dashboard-insight-card-* / dashboard-empty-import / dashboard-top-riders /
 *   rider-list-status-scope / dashboard-abnormal-view-all / order-attention-active /
 *   dashboard-lock-title|overdue|remaining|view-all / period-lock-due-scope /
 *   plan-activate-not-full-trial / trial-full-not-payroll /
 *   trial-binding-fixed-full-amount / period-fixed-amount-full-once /
 *   trial-matches-official-calculate。
 * exclude_attention 须拿掉明细行（#20）；金标 C03/C04/C05A/C17 不得 skip。
 * Cycle 3：#23 后端 + #24 钩子不得 skip；C08/C05B/C11 金标；calc-riders 搜第 201 人。
 * Cycle 4：#27 选择器缺失即红，不得 skip。金标 8200/7800/3500 不改。
 * Cycle 5：status 钩子落地才强制新 testid；未落地断言计划合同（显示空日 / 绑定 Tab / 手工加项硬拦）。不得 skip。
 * trial-binding-segments 无数字 = FAIL（不得 WARN 过）。
 * 旧 import/stale spec 已改「完成」语义（夹具无方案骑手不得纯绿完成）。
 * 叠 PR #18+#19+#20+#21+#23+#24+#26+#27+#28：Cycle 1/2/3/4 CDP。Cycle 5 叠本文件。
 * #27 选择器缺失即红，不得 skip。金标 8200/7800/3500 不改。
 * queued 阈值替身：CDP_QUEUED_RIDER_THRESHOLD（默认 2）或 Playwright 拦截 queued=true。
 * 侧栏泄漏保持已知红，本 harness 不改断言。
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

/**
 * 截图证据。默认 fullPage；证据场景可传 opts：
 *   { fullPage, timeout, optional }
 * optional=true → 失败只 WARN，不推翻已绿功能断言。
 */
export async function shot(page, name, opts = {}) {
  const {
    fullPage = true,
    timeout = 30_000,
    optional = false,
  } = opts;
  fs.mkdirSync(CONFIG.mediaDir, { recursive: true });
  const file = path.join(CONFIG.mediaDir, `${name}.png`);
  try {
    await page.screenshot({ path: file, fullPage, timeout });
    console.log('SHOT', file);
    return file;
  } catch (err) {
    if (optional) {
      console.warn(`SHOT optional skip: ${name}`, err.message);
      return null;
    }
    throw err;
  }
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
    console.log('灌种：node scripts/cdp/seed-xiaoxiang-fixtures.mjs');
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

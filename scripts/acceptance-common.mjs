/**
 * 管理端 / 骑手 H5 验收脚本的公共部分。
 *
 * 路径相对本文件（import.meta.url），不写死本机用户目录。
 * 账号密码读环境变量；未设置时用本机演示账号（见 scripts/README.md）。
 * 登录只走真实登录页，验证码从 Redis 读取，不调用 /auth/login/swagger。
 */
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.resolve(SCRIPT_DIR, '..');

const uiRequire = createRequire(path.join(ROOT, 'fastapi-best-architecture-ui/package.json'));
const { chromium } = uiRequire('playwright');

export const API = trimSlash(process.env.QIPAY_API_BASE || 'http://127.0.0.1:8000');
export const ADMIN = trimSlash(process.env.QIPAY_ADMIN_BASE || 'http://localhost:5173');
export const H5 = trimSlash(process.env.QIPAY_H5_BASE || 'http://localhost:5174');

export const ADMIN_USER = process.env.QIPAY_ADMIN_USER || 'admin';
export const ADMIN_PASSWORD = process.env.QIPAY_ADMIN_PASSWORD || '123456';
export const RIDER_USER = process.env.QIPAY_RIDER_USER || 'D5A001';
export const RIDER_PASSWORD = process.env.QIPAY_RIDER_PASSWORD || 'Rider@123456';

const CAPTCHA_PREFIX = process.env.QIPAY_CAPTCHA_PREFIX || 'fba:login:captcha';
const REDIS_CLI = process.env.QIPAY_REDIS_CLI || 'redis-cli';
const NOTICE_PREFIX = 'P111验收';

function trimSlash(value) {
  return value.replace(/\/+$/, '');
}

export function shotDir(fallbackName) {
  const fromEnv = process.env.QIPAY_SHOT_DIR;
  const dir = fromEnv || path.join(ROOT, '.runtime', 'acceptance', fallbackName);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

export function createRunner() {
  const failures = [];
  const breakPage = process.env.QIPAY_BREAK_PAGE || '';
  const breakText = process.env.QIPAY_BREAK_TEXT || '不可能出现的验收文案';
  const failFast = process.env.QIPAY_FAIL_FAST === '1';

  function fail(message) {
    failures.push(message);
    console.error('FAIL', message);
    if (failFast) {
      const error = new Error(message);
      error.failFast = true;
      throw error;
    }
  }

  return { breakPage, breakText, fail, failures };
}

export async function launchBrowser() {
  return chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
}

export async function assertReachable(url, name) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(8000) });
    if (response.status >= 500) {
      throw new Error(`HTTP ${response.status}`);
    }
  } catch (error) {
    throw new Error(`${name}不可用（${url}）：${error.message}`);
  }
}

function isLocalApp(url) {
  try {
    const host = new URL(url).hostname;
    return host === '127.0.0.1' || host === 'localhost';
  } catch {
    return false;
  }
}

function ignoreHttp(url) {
  return url.includes('favicon') || url.endsWith('.map') || url.includes('chrome-extension://');
}

export function attachHttpGuard(page) {
  const buckets = [];
  page.on('request', (request) => {
    if (request.url().includes('/auth/login/swagger')) {
      const bucket = buckets.at(-1);
      bucket?.push(`禁止请求 swagger 登录：${request.url()}`);
    }
  });
  page.on('response', (response) => {
    const status = response.status();
    if (status < 400) return;
    const url = response.url();
    if (!isLocalApp(url) || ignoreHttp(url)) return;
    const bucket = buckets.at(-1);
    bucket?.push(`${status} ${url}`);
  });
  return {
    start() {
      const bucket = [];
      buckets.push(bucket);
      return bucket;
    },
    stop() {
      buckets.pop();
    },
  };
}

export async function shot(page, dir, name) {
  const file = path.join(dir, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  console.log('SHOT', file);
  return file;
}

function readCaptchaCode(uuid) {
  const output = execFileSync(REDIS_CLI, ['GET', `${CAPTCHA_PREFIX}:${uuid}`], {
    encoding: 'utf8',
  }).trim();
  if (!output || output === '(nil)') {
    throw new Error(`Redis 中没有验证码：${CAPTCHA_PREFIX}:${uuid}`);
  }
  return output;
}

function trackCaptcha(page) {
  let latest = null;
  const onResponse = async (response) => {
    if (!response.url().includes('/api/v1/auth/captcha')) return;
    if (response.status() !== 200) return;
    try {
      const body = await response.json();
      if (body?.data?.uuid) latest = body.data;
    } catch {
      // 验证码响应体由页面自己消费；这里读失败就继续等下一次。
    }
  };
  page.on('response', onResponse);
  return {
    async latestAfter(previousUuid, timeout = 20000) {
      const started = Date.now();
      while (Date.now() - started < timeout) {
        if (latest?.uuid && latest.uuid !== previousUuid) return latest;
        await page.waitForTimeout(100);
      }
      throw new Error('登录页没有拿到新的验证码');
    },
    stop() {
      page.off('response', onResponse);
    },
  };
}

async function loginViaForm(page, { open, ready, fill, submit, success }) {
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    const tracker = trackCaptcha(page);
    try {
      await open();
      await ready();
      const detail = await tracker.latestAfter(null);
      const code = detail.is_enabled === false ? '' : readCaptchaCode(detail.uuid);
      await fill(code);
      const loginResponse = page.waitForResponse(
        (response) =>
          response.url().includes('/api/v1/auth/login') &&
          !response.url().includes('/auth/login/swagger') &&
          response.request().method() === 'POST',
        { timeout: 20000 },
      );
      await submit();
      const response = await loginResponse;
      if (response.status() === 429) {
        console.log('登录接口限流，65 秒后重试');
        await page.waitForTimeout(65000);
        continue;
      }
      if (response.status() >= 400) {
        const text = await response.text().catch(() => '');
        throw new Error(`登录失败 HTTP ${response.status()}：${text.slice(0, 300)}`);
      }
      let body = null;
      try {
        body = await response.json();
      } catch {
        body = null;
      }
      if (body && body.code && body.code !== 200) {
        throw new Error(`登录失败：${body.msg || body.code}`);
      }
      await success();
      return;
    } finally {
      tracker.stop();
    }
  }
  throw new Error('登录连续被限流');
}

export async function loginAdmin(page) {
  await loginViaForm(page, {
    open: () => page.goto(`${ADMIN}/auth/login`, { waitUntil: 'domcontentloaded', timeout: 60000 }),
    ready: () => page.locator('input[name="captcha"]').waitFor({ timeout: 20000 }),
    fill: async (code) => {
      await page.locator('input[name="username"]').fill(ADMIN_USER);
      await page.locator('input[name="password"]').fill(ADMIN_PASSWORD);
      if (code) await page.locator('input[name="captcha"]').fill(code);
    },
    submit: () => page.locator('button[aria-label="login"]').click(),
    success: async () => {
      await page.waitForURL((url) => !url.pathname.includes('/auth/login'), { timeout: 30000 });
      console.log('OK 管理端已通过登录页进入', page.url());
    },
  });
}

export async function loginH5(page) {
  await loginViaForm(page, {
    open: () => page.goto(`${H5}/login`, { waitUntil: 'domcontentloaded', timeout: 60000 }),
    ready: async () => {
      await page.getByRole('heading', { name: '骑手薪资' }).waitFor({ timeout: 20000 });
      await page.getByPlaceholder('点击图片可刷新').waitFor({ timeout: 20000 });
    },
    fill: async (code) => {
      await page.getByPlaceholder('请输入工号').fill(RIDER_USER);
      await page.getByPlaceholder('请输入密码').fill(RIDER_PASSWORD);
      if (code) await page.getByPlaceholder('点击图片可刷新').fill(code);
    },
    submit: () => page.getByRole('button', { name: '登录', exact: true }).click(),
    success: async () => {
      await page.waitForURL((url) => url.pathname.startsWith('/home'), { timeout: 30000 });
      console.log('OK 骑手 H5 已通过登录页进入', page.url());
    },
  });
}

export async function readAdminToken(page) {
  const token = await page.evaluate(() => {
    for (const key of Object.keys(localStorage)) {
      try {
        const data = JSON.parse(localStorage.getItem(key) || '');
        if (data && typeof data.accessToken === 'string' && data.accessToken) {
          return data.accessToken;
        }
      } catch {
        // 不是 JSON 会话。
      }
    }
    return '';
  });
  if (!token) throw new Error('登录页成功后没有读到 accessToken');
  return token;
}

export async function apiJson(token, method, pathname, body) {
  const response = await fetch(`${API}${pathname}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = null;
  }
  if (response.status >= 400 || (json && json.code && json.code !== 200)) {
    throw new Error(`${method} ${pathname} 失败 HTTP ${response.status}：${text.slice(0, 300)}`);
  }
  return json;
}

export async function resolveDemo(token) {
  const sites = await apiJson(token, 'GET', '/api/v1/rider-salary/sites/all');
  const siteList = sites?.data || [];
  const site = siteList.find((item) => item.code === 'D5A') || siteList[0];
  if (!site?.id) throw new Error('没有可用站点，无法打开带站点参数的页面');
  const riders = await apiJson(
    token,
    'GET',
    `/api/v1/rider-salary/riders?page=1&size=20&keyword=${encodeURIComponent(RIDER_USER)}`,
  );
  const riderList = riders?.data?.items || [];
  const rider = riderList.find((item) => item.job_no === RIDER_USER) || riderList[0];
  if (!rider?.id) throw new Error(`没有找到骑手 ${RIDER_USER}`);
  const periods = await apiJson(
    token,
    'GET',
    `/api/v1/rider-salary/periods?page=1&size=5&site_id=${site.id}`,
  );
  const period = periods?.data?.items?.[0] || null;
  return { period, rider, site };
}

async function listProbeNotices(token) {
  const listed = await apiJson(
    token,
    'GET',
    `/api/v1/rider-salary/notices?page=1&size=50&title=${encodeURIComponent(NOTICE_PREFIX)}`,
  );
  return (listed?.data?.items || []).filter((item) => String(item.title || '').startsWith(NOTICE_PREFIX));
}

export async function cleanupProbeNotices(token) {
  const items = await listProbeNotices(token);
  for (const item of items) {
    await apiJson(token, 'DELETE', `/api/v1/rider-salary/notices/${item.id}`);
    console.log('CLEAN', item.id, item.title);
  }
}

function textsFor(runner, name, texts) {
  if (runner.breakPage && runner.breakPage === name) return [runner.breakText];
  return texts;
}

export async function visitPage(page, guard, runner, dir, spec) {
  const bucket = guard.start();
  try {
    const response = await page.goto(spec.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    if (response && response.status() >= 400) {
      runner.fail(`${spec.name} 页面响应 HTTP ${response.status()}`);
    }
    await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
    const texts = textsFor(runner, spec.name, spec.texts);
    for (const text of texts) {
      try {
        await page
          .getByText(text, { exact: false })
          .filter({ visible: true })
          .first()
          .waitFor({ state: 'visible', timeout: 20000 });
      } catch {
        runner.fail(`${spec.name} 缺少关键文本：${text}`);
      }
    }
    if (spec.urlIncludes && !page.url().includes(spec.urlIncludes)) {
      runner.fail(`${spec.name} 地址不正确：${page.url()}`);
    }
    for (const banned of spec.banned || []) {
      if (await page.getByText(banned, { exact: false }).filter({ visible: true }).count()) {
        runner.fail(`${spec.name} 出现失败文案：${banned}`);
      }
    }
    await page.waitForTimeout(300);
    if (bucket.length) {
      runner.fail(`${spec.name} 出现 4xx/5xx：${bucket.join(' | ')}`);
    } else if (!runner.failures.some((item) => item.startsWith(`${spec.name} `))) {
      console.log('OK', spec.name);
    }
    if (spec.shot) await shot(page, dir, spec.shot);
  } finally {
    guard.stop();
  }
}

function noticeRows(page) {
  return page.locator('.vxe-table--main-wrapper .vxe-body--row');
}

async function clickRowAction(page, title, action) {
  const rows = noticeRows(page);
  await rows.first().waitFor({ timeout: 15000 });
  const count = await rows.count();
  let index = -1;
  for (let i = 0; i < count; i += 1) {
    const text = await rows.nth(i).innerText();
    if (text.includes(title)) {
      index = i;
      break;
    }
  }
  if (index < 0) throw new Error(`公告列表中没有「${title}」`);
  const inRow = rows.nth(index).getByText(action, { exact: true });
  if (await inRow.count()) {
    await inRow.first().click();
    return;
  }
  const fixed = page.locator('.vxe-table--fixed-right-wrapper .vxe-body--row');
  await fixed.nth(index).getByText(action, { exact: true }).click();
}

export async function assertNoticeRoundtrip(page, guard, runner, dir, token) {
  const name = '公告写操作';
  const title = `${NOTICE_PREFIX}${Date.now()}`;
  const content = '验收脚本临时公告，创建后立即删除，不发布。';
  const bucket = guard.start();
  try {
    await page.goto(`${ADMIN}/rider-salary/notice`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.getByRole('button', { name: '新增公告' }).click();
    const dialog = page.getByRole('dialog').last();
    await dialog.getByText('新增公告', { exact: false }).first().waitFor({ timeout: 10000 });
    await dialog.locator('input:visible').first().fill(title);
    await dialog.locator('textarea').fill(content);
    await dialog.getByRole('button', { name: /确\s*认/ }).click();
    const createdRow = noticeRows(page).filter({ hasText: title });
    await createdRow.first().waitFor({ timeout: 15000 });

    const created = (await listProbeNotices(token)).find((item) => item.title === title);
    const rowText = await createdRow.first().innerText();
    if (!created) {
      runner.fail(`${name} 创建后接口列表没有这条公告`);
    } else if (created.status !== 'draft' || created.status_label !== '草稿') {
      runner.fail(
        `${name} 新建后状态应为草稿，实际 status=${created.status} label=${created.status_label}`,
      );
    } else if (!rowText.includes('草稿')) {
      runner.fail(`${name} 页面行内没有「草稿」：${rowText}`);
    } else {
      console.log('OK', name, '已创建草稿', created.id);
    }

    await clickRowAction(page, title, '删除');
    await page.getByText(`确定删除 ${title}`, { exact: false }).waitFor({ timeout: 8000 });
    await page.getByRole('button', { name: /确\s*定/ }).click();
    await createdRow.waitFor({ state: 'hidden', timeout: 15000 }).catch(async () => {
      if (await createdRow.count()) {
        runner.fail(`${name} 删除后页面仍能看到标题`);
      }
    });
    const left = (await listProbeNotices(token)).find((item) => item.title === title);
    if (left) {
      runner.fail(`${name} 删除后接口仍返回该公告 id=${left.id}`);
    } else {
      console.log('OK', name, '已删除', title);
    }
    await page.waitForTimeout(300);
    if (bucket.length) runner.fail(`${name} 出现 4xx/5xx：${bucket.join(' | ')}`);
    await shot(page, dir, '公告-新建并删除');
  } catch (error) {
    if (error?.failFast) throw error;
    runner.fail(`${name} 未完成：${error.message}`);
    await shot(page, dir, '公告-写操作失败').catch(() => {});
  } finally {
    guard.stop();
    await cleanupProbeNotices(token).catch((error) => {
      console.error('CLEAN FAIL', error.message);
    });
  }
}

export function finish(runner) {
  if (runner.failures.length) {
    console.error(`失败 ${runner.failures.length} 项`);
    for (const item of runner.failures) console.error(' -', item);
    return 1;
  }
  console.log('全部通过');
  return 0;
}

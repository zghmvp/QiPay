/**
 * Cycle 13 CDP 共用。具名五席，不得扩第六句。
 * 钩子缺失即红，不得 skip。禁止截图即绿。禁止 API importCsv 冒充向导绿。
 * 金标 8200 / 7800 / 3500 已锁。不改 trial-case-gold 产品句。
 * 不写产品 UI。不改 FBA。不改决策 29 写禁。不改次数规则。
 */
import fs from 'node:fs';
import path from 'node:path';

export const GOLD_C03_GROSS = 8200;
export const GOLD_C04_GROSS = 7800;
export const GOLD_C05A_GROSS = 3500;
export const GOLD_C17_PERIOD_AMOUNT = 2310;
export const GOLD_C17_PLAN_AMOUNT = 100;

export const GOLD_LOCKED = {
  C03: GOLD_C03_GROSS,
  C04: GOLD_C04_GROSS,
  C05A: GOLD_C05A_GROSS,
};

export const LOCKED_GOLD_FORBIDDEN = /4629\.33|预支\s*800/;
export const IMPORT_NOT_PAYROLL_COPY = /导入完成\s*≠\s*已出账/;
export const FILE_REQUIRED_422 = /file\s*字段为必填项|字段为必填项/;
export const MONTH_TOTAL_COPY = /本月合计/;
export const CROSS_PERIOD_COPY = /跨\s*\d+\s*个周期|本月合计\s*\/\s*\d+\s*个周期/;
export const PERIOD_PAYSLIP_COPY = /本周期|本期工资条|本期应发/;
export const PERIOD_VALID_LABEL = '周期有效单量';
export const PLAN_PERIOD_LABEL = '方案期内单量';
export const SKIP_RIDER_COPY = /骑手级已覆盖|跳过骑手级覆盖/;
export const ADVANCE_PENDING_TITLE = '待审核预支';

export const LIGHTHOUSE_XLSX_NAME = 'lighthouse-orders-2026-09-15.xlsx';

export const MUST1_WIZARD_HOOKS = [
  'ops-import-wizard-lighthouse',
  'import-wizard-file',
];
export const MUST1_RESULT_HOOKS = [
  'import-not-payroll',
  'import-goto-calculate',
];

export const MUST2_HOOKS = [
  'cdp-admin-calendar-month-not-payslip',
  'calendar-month-total',
  'calendar-month-period-count',
  'calendar-period-chip',
  'calendar-view-period',
];

export const MUST3_HOOKS = [
  'ops-advance-todo-deeplink',
  'dashboard-advance-row',
  'dashboard-advance-view-all',
];

export const MUST4_HOOKS = [
  'ops-trial-period-vs-plan-order-count',
  'trial-valid-order-count',
  'trial-plan-order-count',
];

export const MUST5_HOOKS = [
  'ops-lock-confirm-skip-rider-level',
  'period-lock-confirm-hint',
  'period-lock-skip-count',
];

export const NAMED_SPECS = [
  'ops-import-wizard-lighthouse',
  'cdp-admin-calendar-month-not-payslip',
  'ops-advance-todo-deeplink',
  'ops-trial-period-vs-plan-order-count',
  'ops-lock-confirm-skip-rider-level',
];

export function assertLockedGoldUnchanged() {
  if (
    GOLD_LOCKED.C03 !== 8200 ||
    GOLD_LOCKED.C04 !== 7800 ||
    GOLD_LOCKED.C05A !== 3500
  ) {
    throw new Error('金标 8200/7800/3500 已锁，Cycle 13 不得改数字');
  }
  if (
    GOLD_C17_PERIOD_AMOUNT !== 2310 ||
    GOLD_C17_PLAN_AMOUNT !== 100
  ) {
    throw new Error('C17 对照须为 2310 vs 100，不得 skip、不得新开案例号');
  }
}

export function authHeaders(token, extra = {}) {
  return { Authorization: `Bearer ${token}`, ...extra };
}

export async function apiFetch(apiUrl, token, method, urlPath, body) {
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
  const res = await fetch(`${apiUrl}${urlPath}`, {
    method,
    headers: authHeaders(
      token,
      isForm || body === undefined ? {} : { 'Content-Type': 'application/json' },
    ),
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  });
  const text = await res.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = { raw: text };
  }
  return { res, json, text };
}

export function siteMonth() {
  return {
    siteId: process.env.CDP_SITE_ID || '13',
    month: process.env.CDP_MONTH || '2026-09',
    siteCode: process.env.CDP_SITE_CODE || 'SZ0050',
  };
}

export function parseUrl(raw, base = 'http://127.0.0.1') {
  try {
    return new URL(raw, base);
  } catch {
    return null;
  }
}

export function queryOf(raw, base = 'http://127.0.0.1') {
  const url = parseUrl(raw, base);
  return url ? url.searchParams : new URLSearchParams();
}

export function pathOf(raw, base = 'http://127.0.0.1') {
  const url = parseUrl(raw, base);
  return url ? url.pathname : String(raw || '');
}

export async function requireTestId(page, testId, message, timeout = 15000) {
  const el = page.getByTestId(testId);
  try {
    await el.first().waitFor({ state: 'visible', timeout });
  } catch {
    throw new Error(message || `未见 ${testId}，不得 skip`);
  }
  return el.first();
}

export async function requireHooks(page, testIds, extraMessage) {
  for (const testId of testIds) {
    await requireTestId(
      page,
      testId,
      extraMessage || `未见 Cycle 13 钩子 ${testId}，不得 skip`,
    );
  }
}

export async function waitPath(page, re, timeout = 15000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (re.test(page.url())) return page.url();
    await page.waitForTimeout(150);
  }
  throw new Error(`未跳到 ${re}，实际 ${page.url()}`);
}

export function mediaDir() {
  return (
    process.env.CDP_MEDIA_DIR ||
    path.join(
      process.env.CURSOR_AGENT_STORE ||
        '/cursor/stores/bc-2955b371-f65c-4990-a229-d877e2ac6c7a',
      'media',
    )
  );
}

export function lighthouseXlsxPath() {
  const candidates = [
    process.env.CDP_LIGHTHOUSE_XLSX,
    path.join(mediaDir(), LIGHTHOUSE_XLSX_NAME),
    '/cursor/stores/bc-2955b371-f65c-4990-a229-d877e2ac6c7a/media/lighthouse-orders-2026-09-15.xlsx',
  ].filter(Boolean);
  for (const file of candidates) {
    if (fs.existsSync(file)) return file;
  }
  throw new Error(
    `灯塔样例缺失 ${LIGHTHOUSE_XLSX_NAME}，不得 skip、不得改用 CSV/API。已查：${candidates.join(' | ')}`,
  );
}

export async function pickAntOption(page, root, optionRe) {
  const select = root.locator('.ant-select').first();
  await select.click();
  const opt = page
    .locator('.ant-select-dropdown:visible .ant-select-item-option')
    .filter({ hasText: optionRe })
    .first();
  await opt.waitFor({ state: 'visible', timeout: 15000 });
  await opt.click();
}

export async function openImportWizard(page) {
  await page.getByRole('button', { name: /^导入$/ }).first().click();
  const dialog = page.getByRole('dialog').or(page.locator('[data-slot="dialog-content"]')).last();
  await dialog.waitFor({ state: 'visible', timeout: 20000 });
  return dialog;
}

export function assertImportUsedRealFile(request, response) {
  const url = request.url();
  if (!/\/api\/v1\/rider-salary\/orders\/import(?:\?|$)/.test(url)) {
    throw new Error(`Must 1 须 POST /orders/import。实际 ${url}`);
  }
  const ctype = request.headers()['content-type'] || request.headers()['Content-Type'] || '';
  if (!/multipart\/form-data/i.test(ctype)) {
    throw new Error(
      `Must 1 请求须带 multipart file。JSON/无文件/importCsv 冒充绿 = FAIL。content-type=${ctype}`,
    );
  }
  const status = response.status();
  const body = response._cycle13BodyText || '';
  if (status === 422 && FILE_REQUIRED_422.test(body)) {
    throw new Error(`仍 422「file 字段为必填项」= FAIL。${body.slice(0, 300)}`);
  }
  if (status < 200 || status >= 300) {
    throw new Error(
      `向导导入须 2xx 进入结果步。HTTP ${status}：${body.slice(0, 300)}`,
    );
  }
}

export function calendarPeriodPayslipTarget(riderId, periodId, payrollId) {
  if (payrollId) {
    return { path: `/rider-salary/payroll/${payrollId}`, query: {} };
  }
  if (!riderId || !periodId) {
    throw new Error('芯片/查看周期须带 rider_id + period_id，不得 skip');
  }
  return {
    path: '/rider-salary/payroll',
    query: { rider_id: String(riderId), period_id: String(periodId) },
  };
}

export function isPeriodDrawer(raw) {
  const pathname = pathOf(raw);
  const params = queryOf(raw);
  if (/\/rider-salary\/payroll(?:\/|$)/.test(pathname)) return false;
  const onList = /\/rider-salary\/period\/?$/.test(pathname);
  return onList && Boolean(params.get('id') || params.get('period_id'));
}

export function isRiderPeriodPayslip(raw, { riderId, periodId } = {}) {
  const pathname = pathOf(raw);
  const params = queryOf(raw);
  const detail = pathname.match(/\/rider-salary\/payroll\/(\d+)/);
  if (detail) return true;
  if (!/\/rider-salary\/payroll\/?$/.test(pathname)) return false;
  if (riderId && params.get('rider_id') !== String(riderId)) return false;
  if (periodId && params.get('period_id') !== String(periodId)) return false;
  return Boolean(params.get('rider_id') && params.get('period_id'));
}

export function assertChipGoesToPayslip(raw, { riderId, periodId, label = '周期芯片' }) {
  if (isPeriodDrawer(raw)) {
    throw new Error(
      `${label} 只开 /period?id= 全站抽屉 = FAIL。须 /payroll/:id 或 /payroll?rider_id=&period_id=。实际 ${raw}`,
    );
  }
  if (!isRiderPeriodPayslip(raw, { riderId, periodId })) {
    throw new Error(
      `${label} 须落到该骑手该周期条。实际 ${raw}`,
    );
  }
}

export function pendingAdvanceRowTarget(advanceId) {
  if (!advanceId) {
    throw new Error('预支待办行须带该条 id，不得 skip');
  }
  return {
    path: '/rider-salary/advance',
    query: { id: String(advanceId), status: 'pending' },
  };
}

export function pendingAdvancesViewAllTarget(siteId, month) {
  const query = { status: 'pending' };
  if (siteId != null && Number(siteId) > 0) query.site_id = String(siteId);
  if (month) query.month = month;
  return { path: '/rider-salary/advance', query };
}

export function isAdvanceRow(raw, advanceId) {
  const pathname = pathOf(raw);
  const params = queryOf(raw);
  if (!/\/rider-salary\/advance\/?$/.test(pathname)) return false;
  return params.get('id') === String(advanceId);
}

export function isAdvanceViewAll(raw, { siteId, month } = {}) {
  const pathname = pathOf(raw);
  const params = queryOf(raw);
  if (!/\/rider-salary\/advance\/?$/.test(pathname)) return false;
  if (params.get('status') && params.get('status') !== 'pending') return false;
  if (siteId && params.get('site_id') !== String(siteId)) return false;
  if (!siteId && params.get('site_id')) return false;
  if (month && params.get('month') !== month) return false;
  return true;
}

export function assertAdvanceRowOpensThis(raw, advanceId) {
  if (!isAdvanceRow(raw, advanceId)) {
    throw new Error(
      `点行须办这一条（带 id=${advanceId}）。进总列表且无该条打开 = FAIL。实际 ${raw}`,
    );
  }
}

export function assertAdvanceViewAllScoped(raw, { siteId, month }) {
  if (!isAdvanceViewAll(raw, { siteId, month })) {
    throw new Error(
      `查看全部须带当前站月。不带站月 / 超管串站 = FAIL。实际 ${raw}`,
    );
  }
}

export function lockConfirmHintFromPreflight(preflight) {
  const orderCount = Number(
    preflight?.order_count ?? preflight?.freeze_order_count ?? 0,
  );
  const adjCount = Number(
    preflight?.adjustment_count ?? preflight?.freeze_adjustment_count ?? 0,
  );
  const payrollCount = Number(
    preflight?.payroll_count ?? preflight?.freeze_payroll_count ?? 0,
  );
  const lockRiders = Number(preflight?.lock_rider_count ?? 0);
  const skipRiders = Number(preflight?.skip_rider_count ?? 0);
  return (
    `将冻结订单 ${orderCount}、奖惩 ${adjCount}、薪资单 ${payrollCount}。` +
    `将锁骑手 ${lockRiders} 人。跳过骑手级覆盖 ${skipRiders} 人。`
  );
}

export function assertLockConfirmCopy(text, preflight) {
  const blob = String(text || '');
  if (!/订单/.test(blob) || !/奖惩/.test(blob) || !/薪资/.test(blob)) {
    throw new Error(`锁确认须写出将冻结订单/奖惩/薪资单数。实际：${blob.slice(0, 300)}`);
  }
  if (!SKIP_RIDER_COPY.test(blob)) {
    throw new Error(
      `锁确认须出现「骑手级已覆盖 / 跳过骑手级覆盖」（M 可为 0）。实际：${blob.slice(0, 300)}`,
    );
  }
  if (preflight) {
    const skip = Number(preflight.skip_rider_count);
    if (Number.isFinite(skip) && !blob.includes(String(skip))) {
      throw new Error(`跳过人数须以后端预检为准，须出现 M=${skip}。实际：${blob.slice(0, 300)}`);
    }
  }
}

export async function fetchDashboardSummary(apiUrl, token, { siteId, month }) {
  const qs = new URLSearchParams();
  if (siteId) qs.set('site_id', String(siteId));
  if (month) qs.set('month', month);
  const { res, json } = await apiFetch(
    apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/dashboard/summary?${qs}`,
  );
  if ([404, 405, 501].includes(res.status)) {
    throw new Error(`工作台摘要缺失 HTTP ${res.status}，不得 skip`);
  }
  return json?.data;
}

export async function fetchPeriods(apiUrl, token, params) {
  const qs = new URLSearchParams({ page: '1', size: '50' });
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && value !== '') qs.set(key, String(value));
  }
  const { res, json } = await apiFetch(
    apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/periods?${qs}`,
  );
  if ([404, 405, 501].includes(res.status)) {
    throw new Error(`周期列表缺失 HTTP ${res.status}，不得 skip`);
  }
  return { res, json, items: json?.data?.items || [] };
}

export async function trialVersion(apiUrl, token, versionId, { riderId, start, end, mode }) {
  return apiFetch(
    apiUrl,
    token,
    'POST',
    `/api/v1/rider-salary/plan-versions/${versionId}/trial`,
    {
      rider_id: Number(riderId),
      start_date: start,
      end_date: end,
      // 月中换绑分叉须按绑定分段；整版强制全程生效两数永远相等 = FAIL
      mode: mode || 'binding_segments',
    },
  );
}

export function trialOrderCounts(json) {
  const summary = json?.data?.summary || json?.summary || {};
  const periodValid = Number(
    summary.period_valid_order_count ?? summary.valid_order_count,
  );
  const planPeriod = Number(
    summary.plan_period_order_count ?? summary.plan_order_count,
  );
  return { periodValid, planPeriod, orderCount: Number(summary.order_count) };
}

export async function expandPanel(page, title) {
  const header = page.locator('.ant-collapse-header').filter({ hasText: title }).first();
  const byRole = page.getByRole('button', { name: new RegExp(title) });
  if (await header.count()) {
    await header.waitFor({ state: 'visible', timeout: 20000 });
    await header.click();
    return;
  }
  if (await byRole.count()) {
    await byRole.first().click();
    return;
  }
  throw new Error(`未找到工作台「${title}」折叠头，不得 skip`);
}

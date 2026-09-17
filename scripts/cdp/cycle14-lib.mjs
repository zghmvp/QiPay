/**
 * Cycle 14 CDP 共用。具名五席，不得扩第六句。
 * 钩子缺失即红，不得 skip。禁止截图即绿。禁止 API importCsv 冒充向导绿。
 * Must 2 必须走工作台缺口行 → 向导，禁止只断言订单列表带日。
 * Must 4 必须走向导 + 跳过错误行；把本席写成「仍 422」= FAIL。
 * Must 5 不验收 Cycle 13 芯片 / 查看周期进条。
 * 金标 8200 / 7800 / 3500 已锁。不改 trial-case-gold 产品句。
 * 不写产品 UI。不改 FBA。不改决策 29。不改 #9 缺口谓词。不改 attention 谓词。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const GOLD_C03_GROSS = 8200;
export const GOLD_C04_GROSS = 7800;
export const GOLD_C05A_GROSS = 3500;

export const GOLD_LOCKED = {
  C03: GOLD_C03_GROSS,
  C04: GOLD_C04_GROSS,
  C05A: GOLD_C05A_GROSS,
};

export const LOCKED_GOLD_FORBIDDEN = /4629\.33|预支\s*800/;
export const IMPORT_NOT_PAYROLL_COPY = /导入完成\s*≠\s*已出账/;
export const ALL_SUCCESS_COPY = /全部导入成功/;
export const SITE_LEVEL_COPY = /站点级/;
export const PERIOD_NOT_DAILY_COPY = /周期项不落日|对账看条/;
export const FORMULA_AMOUNT_LABEL = '公式金额';
export const NET_AMOUNT_LABEL = '净额';
export const SKIP_ERRORS_LABEL = '跳过错误行';
export const GAP_BLOCK_TITLE = '导入覆盖缺口';
export const DUE_BLOCK_TITLE = /即将到期|过期未锁/;
export const STALE_BLOCK_TITLE = /需重算/;
export const ABNORMAL_BLOCK_TITLE = '异常订单';

export const SKIP_ERRORS_CSV_NAME = 'skip-errors-half-success.csv';

export const MUST1_HOOKS = [
  'ops-due-stale-row-level-label',
  'dashboard-due-row',
  'dashboard-stale-row',
  'dashboard-row-level',
  'dashboard-row-rider-name',
];

export const MUST2_HOOKS = [
  'ops-import-gap-wizard-that-day',
  'dashboard-import-gap-row',
  'import-wizard',
  'import-wizard-site',
  'import-wizard-date-from',
  'import-wizard-date-to',
];

export const MUST2_ROW_HOOKS = [
  'ops-import-gap-wizard-that-day',
  'dashboard-import-gap-row',
];

export const MUST2_WIZARD_HOOKS = [
  'import-wizard',
  'import-wizard-site',
  'import-wizard-date-from',
  'import-wizard-date-to',
];

export const MUST3_HOOKS = [
  'ops-abnormal-order-deeplink',
  'dashboard-abnormal-row',
  'dashboard-abnormal-view-all',
];

export const MUST3_LANDING_HOOKS = ['order-detail-open', 'order-row-active'];

export const MUST4_WIZARD_HOOKS = [
  'ops-import-skip-errors-not-all-success',
  'import-skip-errors',
];

export const MUST4_RESULT_HOOKS = [
  'import-success-rows',
  'import-failed-rows',
  'import-not-payroll',
];

export const MUST4_COMPLETE_HOOKS = [
  'import-success-rows',
  'import-failed-rows',
  'import-error-report',
  'import-not-payroll',
];

export const MUST5_HOOKS = [
  'cdp-admin-day-drawer-not-daily-payslip',
  'day-drawer-formula-amount',
  'day-drawer-net',
  'day-drawer-period-not-daily',
];

export const NAMED_SPECS = [
  'ops-due-stale-row-level-label',
  'ops-import-gap-wizard-that-day',
  'ops-abnormal-order-deeplink',
  'ops-import-skip-errors-not-all-success',
  'cdp-admin-day-drawer-not-daily-payslip',
];

export const FIXTURE_SITE_PERIOD_ID = 141001;
export const FIXTURE_RIDER_PERIOD_ID = 141002;
export const FIXTURE_RANGE = '2026-09-01 ~ 2026-09-15';
export const FIXTURE_GAP_DATE = '2026-09-12';
export const FIXTURE_ABNORMAL_ID = 141003;
export const FIXTURE_ABNORMAL_NO = 'C14-ABN-001';
export const FIXTURE_RIDER_NAME = '夹具骑手甲';
export const FIXTURE_RIDER_JOB = 'D5A001';

export function assertLockedGoldUnchanged() {
  if (
    GOLD_LOCKED.C03 !== 8200 ||
    GOLD_LOCKED.C04 !== 7800 ||
    GOLD_LOCKED.C05A !== 3500
  ) {
    throw new Error('金标 8200/7800/3500 已锁，Cycle 14 不得改数字');
  }
}

export function assertNoImportCsvGreen() {
  if (typeof globalThis.importCsv === 'function') {
    throw new Error('本席禁止走 importCsv。API 绿冒充向导交付 = FAIL');
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

export function landingPeriodId(raw) {
  const pathname = pathOf(raw);
  const params = queryOf(raw);
  const calc = pathname.match(/\/rider-salary\/period\/(\d+)\/calculate/);
  if (calc) return calc[1];
  const detail = pathname.match(/\/rider-salary\/period\/(\d+)(?:\/|$)/);
  if (detail) return detail[1];
  return params.get('id') || params.get('period_id') || '';
}

export function isSiteLevelRiderId(riderId) {
  return Number(riderId) === 0;
}

export function isDueRowLanding(raw, periodId) {
  const pathname = pathOf(raw);
  const id = landingPeriodId(raw);
  if (String(id) !== String(periodId)) return false;
  if (/\/calculate(?:\/|$)/.test(pathname)) return false;
  return /\/rider-salary\/period(?:\/|$)/.test(pathname);
}

export function isStaleRowLanding(raw, periodId) {
  const pathname = pathOf(raw);
  const id = landingPeriodId(raw);
  return (
    String(id) === String(periodId) &&
    /\/rider-salary\/period\/\d+\/calculate/.test(pathname)
  );
}

export function isOrderListOnlyLanding(raw) {
  const pathname = pathOf(raw);
  return /\/rider-salary\/order\/?$/.test(pathname);
}

export function isCalendarLanding(raw) {
  return /\/rider-salary\/calendar(?:\/|$|\?)/.test(pathOf(raw));
}

export function isImportGapWizardPrefill({ siteId, date, dateFrom, dateTo }) {
  if (!date) return false;
  if (String(dateFrom || '') !== String(date)) return false;
  if (String(dateTo || '') !== String(date)) return false;
  if (siteId != null && Number(siteId) > 0 && Number.isNaN(Number(siteId))) {
    return false;
  }
  return true;
}

export function isAbnormalRowLanding(raw, { id, orderNo } = {}) {
  const pathname = pathOf(raw);
  const params = queryOf(raw);
  if (!/\/rider-salary\/order(?:\/|$)/.test(pathname)) return false;
  if (id != null && (params.get('id') === String(id) || pathname.endsWith(`/${id}`))) {
    return true;
  }
  if (orderNo && params.get('order_no') === String(orderNo)) return true;
  return false;
}

export function isAbnormalViewAll(raw, { siteId, month } = {}) {
  const pathname = pathOf(raw);
  const params = queryOf(raw);
  if (!/\/rider-salary\/order\/?$/.test(pathname)) return false;
  if (params.get('attention') !== '1') return false;
  if (params.get('status') === 'abnormal' && params.get('attention') !== '1') {
    return false;
  }
  if (siteId != null && params.get('site_id') !== String(siteId)) return false;
  if (month) {
    const from = params.get('date_from') || params.get('month') || '';
    if (!String(from).startsWith(month) && params.get('month') !== month) {
      return false;
    }
  }
  return true;
}

export function isHalfSuccessCopy(text, { failedRows } = {}) {
  const blob = String(text || '');
  if (Number(failedRows) > 0 && ALL_SUCCESS_COPY.test(blob)) return false;
  if (Number(failedRows) > 0 && !/失败/.test(blob) && !String(failedRows).split('').length) {
    return false;
  }
  return true;
}

export function isDayDrawerNotDailyPayslip(text) {
  return PERIOD_NOT_DAILY_COPY.test(String(text || ''));
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

export async function requireAnyTestId(page, testIds, message, timeout = 15000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    for (const testId of testIds) {
      const el = page.getByTestId(testId);
      if (await el.first().isVisible().catch(() => false)) {
        return el.first();
      }
    }
    await page.waitForTimeout(200);
  }
  throw new Error(message || `未见 ${testIds.join(' / ')}，不得 skip`);
}

export async function requireHooks(page, testIds, extraMessage) {
  for (const testId of testIds) {
    await requireTestId(
      page,
      testId,
      extraMessage || `未见 Cycle 14 钩子 ${testId}，不得 skip`,
    );
  }
}

export async function waitPath(page, re, timeout = 15000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (re.test(page.url())) return page.url();
    await page.waitForTimeout(150);
  }
  throw new Error(`等待路径 ${re} 超时，实际 ${page.url()}，不得 skip`);
}

export async function waitWizardOpen(page, timeout = 15000) {
  const dialog = page
    .getByTestId('import-wizard')
    .or(page.getByRole('dialog').filter({ hasText: /导入订单/ }))
    .first();
  try {
    await dialog.waitFor({ state: 'visible', timeout });
  } catch {
    throw new Error(
      '缺口行须打开现有导入向导。点行无反应 / 只进订单空列表 / 进空日历 = FAIL，不得 skip',
    );
  }
  return dialog;
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
  const dialog = page
    .getByTestId('import-wizard')
    .or(page.getByRole('dialog'))
    .last();
  await dialog.waitFor({ state: 'visible', timeout: 20000 });
  return dialog;
}

export function skipErrorsCsvPath() {
  return path.join(
    __dirname,
    '../../fastapi-best-architecture/backend/plugin/rider_salary/tests/fixtures/ops-import-skip-errors-not-all-success',
    SKIP_ERRORS_CSV_NAME,
  );
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

export async function expandPanel(page, title) {
  const re = title instanceof RegExp ? title : new RegExp(title);
  const header = page.locator('.ant-collapse-header').filter({ hasText: re }).first();
  const byRole = page.getByRole('button', { name: re });
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

export function assertDueStaleLevelLabels({ siteText, riderText, riderName }) {
  const site = String(siteText || '');
  const rider = String(riderText || '');
  if (!SITE_LEVEL_COPY.test(site)) {
    throw new Error(
      `站点级行（rider_id=0）必须出现「站点级」类中文。两行只有同一段 range、都无级别 = FAIL。实际：${site.slice(0, 200)}`,
    );
  }
  if (riderName && site.includes(riderName)) {
    throw new Error(`站点级行不得写某个骑手名冒充。实际：${site.slice(0, 200)}`);
  }
  if (riderName && !rider.includes(riderName) && !new RegExp(FIXTURE_RIDER_JOB).test(rider)) {
    throw new Error(
      `骑手级行必须写出该骑手姓名（或工号+姓名）。实际：${rider.slice(0, 200)}`,
    );
  }
  if (!riderName && !SITE_LEVEL_COPY.test(rider) && !/[\u4e00-\u9fff]/.test(rider)) {
    throw new Error(`骑手级行未见姓名/工号。实际：${rider.slice(0, 200)}`);
  }
}

export function assertDueKeepsPeriodId(raw, periodId) {
  if (!isDueRowLanding(raw, periodId)) {
    throw new Error(
      `倒计时点行须带该行 period_id=${periodId}（周期抽屉合法）。落到另一条 / 改走算薪页当唯一落地 = FAIL。实际 ${raw}`,
    );
  }
}

export function assertStaleKeepsPeriodId(raw, periodId) {
  if (!isStaleRowLanding(raw, periodId)) {
    throw new Error(
      `需重算点行须进该期算薪页 period_id=${periodId}。落到另一条 = FAIL。实际 ${raw}`,
    );
  }
}

export function assertGapOpenedWizardNotOrderList(pageUrl, wizardVisible) {
  if (!wizardVisible) {
    if (isCalendarLanding(pageUrl)) {
      throw new Error(
        `缺口行进了 /calendar（空日历或「请选择骑手」）= FAIL。须打开向导并预填该站该日。实际 ${pageUrl}`,
      );
    }
    if (isOrderListOnlyLanding(pageUrl)) {
      throw new Error(
        `缺口行只进订单空列表 / 订单窗而无向导预填 = FAIL。Q14-3 弱落地不另占席。实际 ${pageUrl}`,
      );
    }
    throw new Error('点缺口行无反应、未见导入向导 = FAIL，不得 skip');
  }
}

export function assertWizardPrefill({ siteId, date, dateFrom, dateTo, selectedSiteId }) {
  if (!isImportGapWizardPrefill({ siteId, date, dateFrom, dateTo })) {
    throw new Error(
      `向导须预填该行 site_id + date（date_from=date_to=${date}）。不带该 date / 向导站日是别人的 = FAIL。实际 from=${dateFrom} to=${dateTo} site=${siteId}`,
    );
  }
  if (
    selectedSiteId != null &&
    Number(selectedSiteId) > 0 &&
    siteId != null &&
    Number(siteId) !== Number(selectedSiteId)
  ) {
    throw new Error(
      `已选站时不得串到别站。期望 ${selectedSiteId} 实际 ${siteId}`,
    );
  }
}

export function assertAbnormalRowOpensThis(raw, { id, orderNo }) {
  if (!isAbnormalRowLanding(raw, { id, orderNo })) {
    throw new Error(
      `异常行须办这一条（id=${id} / order_no=${orderNo}）。进月窗全量且无该单打开 = FAIL。实际 ${raw}`,
    );
  }
}

export function assertAbnormalViewAllScoped(raw, { siteId, month }) {
  if (!isAbnormalViewAll(raw, { siteId, month })) {
    throw new Error(
      `查看全部须继续吃 attention=1 + 当前站月。改 attention 谓词 / 只抛 status=abnormal = FAIL。实际 ${raw}`,
    );
  }
}

export function assertHalfSuccessVisible(text, { successRows, failedRows, where }) {
  const blob = String(text || '');
  if (Number(failedRows) > 0 && ALL_SUCCESS_COPY.test(blob)) {
    throw new Error(
      `${where} failed_rows=${failedRows} 仍出现「全部导入成功」= FAIL。实际：${blob.slice(0, 300)}`,
    );
  }
  if (!/\d/.test(blob) || !/失败/.test(blob)) {
    throw new Error(
      `${where} 必须看得见成功行数与失败行数 N。完成步只剩「导入流程已完成」且失败行数消失 = FAIL。实际：${blob.slice(0, 300)}`,
    );
  }
  if (
    Number.isFinite(Number(failedRows)) &&
    Number(failedRows) > 0 &&
    !blob.includes(String(failedRows))
  ) {
    throw new Error(
      `${where} 须出现失败行数 ${failedRows}。把半成功读成整批已入库 = FAIL。实际：${blob.slice(0, 300)}`,
    );
  }
  void successRows;
}

export function assertDayDrawerNotPayslip(text) {
  const blob = String(text || '');
  if (!blob.includes(FORMULA_AMOUNT_LABEL) || !blob.includes(NET_AMOUNT_LABEL)) {
    throw new Error(`日抽屉五卡须能读出「公式金额 / 净额」。实际：${blob.slice(0, 200)}`);
  }
  if (!isDayDrawerNotDailyPayslip(blob)) {
    throw new Error(
      '日抽屉净额无「周期项不落日 / 对账看条」类中文，主数字可被当成当日应发 = FAIL',
    );
  }
  if (LOCKED_GOLD_FORBIDDEN.test(blob)) {
    throw new Error('金标 8200/7800/3500 已锁，不得出现 4629.33 / 预支 800');
  }
}

export function assertSkipErrorsCsvExists() {
  const file = skipErrorsCsvPath();
  if (!fs.existsSync(file) || !file.endsWith(SKIP_ERRORS_CSV_NAME)) {
    throw new Error(
      `Must 4 夹具须为合法行 + 1 行必失败（工号不存在）。未见 ${SKIP_ERRORS_CSV_NAME}，不得 skip`,
    );
  }
  const body = fs.readFileSync(file, 'utf8');
  if (!/NO_SUCH_JOB_C14|工号不存在/.test(body)) {
    throw new Error('跳过错误行夹具须含一行必失败工号，不得 skip');
  }
  return file;
}


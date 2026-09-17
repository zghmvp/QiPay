/**
 * Cycle 4 CDP 共用。钩子对齐 PR #27（status 文件）。
 * 禁止截图即绿；#27 选择器缺失即失败，不得 skip。
 * 金标 8200 / 7800 / 3500 已锁。不新造 XOR / trial-case-gold Must 名。
 * 不写产品 UI。侧栏泄漏不改断言。
 *
 * #27 钩子：
 *   ops-dashboard-insight-card-scope /
 *   dashboard-insight-card-{on_job_riders,month_order_count,month_valid_order_count,
 *     estimated_gross,pending_advances,to_pay_advances} /
 *   dashboard-empty-import / dashboard-top-riders / rider-list-status-scope /
 *   calendar-export-month / ops-calendar-month-export-confirm /
 *   period-export-confirm / period-export-period-row /
 *   ops-dashboard-abnormal-attention-landing / dashboard-abnormal-view-all /
 *   order-attention-active /
 *   ops-dashboard-lock-overdue-visible / dashboard-lock-title /
 *   dashboard-lock-overdue / dashboard-lock-remaining / dashboard-lock-view-all /
 *   period-lock-due-scope /
 *   ops-plan-activate-not-full-trial / trial-full-not-payroll /
 *   trial-binding-fixed-full-amount / plan-activate-not-full-trial /
 *   plan-trial-label / period-fixed-amount-full-once
 */
import { apiFetch, siteMonth } from './cycle1-lib.mjs';
import { GOLD_C03_GROSS, GOLD_C04_GROSS, GOLD_C05A_GROSS } from './cycle2-lib.mjs';

export const GOLD_LOCKED = {
  C03: GOLD_C03_GROSS,
  C04: GOLD_C04_GROSS,
  C05A: GOLD_C05A_GROSS,
};

export const TWO_SEGMENT_FIXED_GROSS = 4000;
export const ALLOC_SEGMENT1_BASE = 933.33;

export const FULL_NOT_BINDING_COPY = /整版试算通过\s*≠\s*按当前绑定出账/;
export const SEGMENT_FULL_AMOUNT_COPY = /本段将按全额计一次/;
/** #27 `trial-binding-fixed-full-amount` / BINDING_FIXED_FULL_AMOUNT */
export const BINDING_FULL_AMOUNT_COPY = /各计一次全额/;
/** #27 ACTIVATE_CONFIRM_CONTENT */
export const ACTIVATE_EVERY_SEGMENT_COPY = /每段各计一次全额/;
export const LOCK_TITLE = '锁账倒计时';
export const LOCK_REMAINING_COPY = /剩余\s*\d+\s*天/;
export const LOCK_OVERDUE_COPY = /已过期未锁\s*\d+\s*天/;
export const GREEN_TRIAL_PASSED = /试算通过\s*✓/;
export const EMPTY_IMPORT_COPY = /去导入订单/;

export const INSIGHT_CARD_IDS = {
  onJob: 'dashboard-insight-card-on_job_riders',
  monthOrders: 'dashboard-insight-card-month_order_count',
  validOrders: 'dashboard-insight-card-month_valid_order_count',
  estimatedGross: 'dashboard-insight-card-estimated_gross',
  pendingAdvances: 'dashboard-insight-card-pending_advances',
  toPayAdvances: 'dashboard-insight-card-to_pay_advances',
};

export {
  apiFetch,
  siteMonth,
};

export function parseUrl(raw, base = 'http://127.0.0.1') {
  try {
    return new URL(raw, base);
  } catch {
    return null;
  }
}

export function queryOf(raw, base = 'http://127.0.0.1') {
  const url = parseUrl(raw, base);
  if (!url) return new URLSearchParams();
  return url.searchParams;
}

export function pathOf(raw, base = 'http://127.0.0.1') {
  const url = parseUrl(raw, base);
  return url ? url.pathname : String(raw || '');
}

export function monthWindowInParams(params, month) {
  if (!month) return false;
  if (params.get('month') === month) return true;
  const from = params.get('date_from');
  const to = params.get('date_to');
  return Boolean(from && to && from.startsWith(month) && to.startsWith(month));
}

export function assertSiteMonthInUrl(raw, { siteId, month, siteOptional = false, monthViaWindow = false, label }) {
  const params = queryOf(raw);
  const path = pathOf(raw);
  if (siteId && !siteOptional && params.get('site_id') !== String(siteId)) {
    throw new Error(`${label} 须带当前 site_id=${siteId}。实际 ${path}?${params}`);
  }
  if (month) {
    const ok = monthViaWindow
      ? monthWindowInParams(params, month)
      : params.get('month') === month || monthWindowInParams(params, month);
    if (!ok) {
      throw new Error(
        `${label} 须带当前月份窗${monthViaWindow ? ' date_from/date_to' : ` month=${month}`}。实际 ${path}?${params}`,
      );
    }
  }
}

export function assertNoExportBeforeConfirm(exportUrls, label = '导出') {
  if (exportUrls.length) {
    throw new Error(
      `${label} 确认前不得打 /periods/{id}/export。已发出：${exportUrls.join(' | ')}`,
    );
  }
}

export async function requireTestId(page, testId, message, timeout = 15000) {
  const el = page.getByTestId(testId);
  try {
    await el.first().waitFor({ state: 'visible', timeout });
  } catch {
    throw new Error(message || `未见 ${testId}（#27 钩子），不得 skip`);
  }
  return el.first();
}

export async function waitPath(page, re, timeout = 15000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (re.test(page.url())) return page.url();
    await page.waitForTimeout(150);
  }
  throw new Error(`未跳到 ${re}，实际 ${page.url()}`);
}

export function duePeriodVisible(endDate, today) {
  const end = endDate instanceof Date ? endDate : new Date(`${endDate}T00:00:00`);
  const now = today instanceof Date ? today : new Date(`${today}T00:00:00`);
  const limit = new Date(now);
  limit.setDate(limit.getDate() + 3);
  return end.getTime() <= limit.getTime();
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
  if (!res.ok) throw new Error(`工作台摘要失败 HTTP ${res.status}`);
  return json?.data;
}

export async function fetchOrders(apiUrl, token, params) {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && value !== '') qs.set(key, String(value));
  }
  const { res, json } = await apiFetch(
    apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/orders?${qs}`,
  );
  if ([404, 405, 501].includes(res.status)) {
    throw new Error(`订单列表缺失 HTTP ${res.status}，不得 skip`);
  }
  return { res, json, items: json?.data?.items || [] };
}

export async function fetchRiders(apiUrl, token, params) {
  const qs = new URLSearchParams({ page: '1', size: '20', ...(params || {}) });
  const { res, json } = await apiFetch(
    apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/riders?${qs}`,
  );
  if ([404, 405, 501].includes(res.status)) {
    throw new Error(`骑手列表缺失 HTTP ${res.status}，不得 skip`);
  }
  return { res, json, items: json?.data?.items || [] };
}

export async function assertActivateNotFullTrial(page) {
  const panel = page.getByTestId('ops-plan-activate-not-full-trial');
  const badge = page.getByTestId('trial-full-not-payroll');
  const activate = page.getByTestId('plan-activate-not-full-trial');
  const body = await page.locator('body').innerText();
  const hasCopy = FULL_NOT_BINDING_COPY.test(body);
  const hasPanel = await panel.isVisible().catch(() => false);
  const hasBadge = await badge.isVisible().catch(() => false);
  const hasActivate = await activate.count();
  if (!hasCopy && !hasPanel && !hasBadge && !hasActivate) {
    throw new Error(
      '未见 #27 钩子 ops-plan-activate-not-full-trial / trial-full-not-payroll / plan-activate-not-full-trial，或文案「整版试算通过 ≠ 按当前绑定出账」。不得 skip',
    );
  }
  if (hasBadge) {
    const text = await badge.innerText();
    if (!FULL_NOT_BINDING_COPY.test(text)) {
      throw new Error(`trial-full-not-payroll 须含「整版试算通过 ≠ 按当前绑定出账」：${text}`);
    }
  }
  const label = page.getByTestId('plan-trial-label');
  if (await label.count()) {
    const text = await label.innerText();
    if (GREEN_TRIAL_PASSED.test(text) && !FULL_NOT_BINDING_COPY.test(text)) {
      throw new Error(`plan-trial-label 不得绿成「试算通过 ✓」冒充出账：${text}`);
    }
  }
}

export function assertLockedGoldUnchanged() {
  if (GOLD_LOCKED.C03 !== 8200 || GOLD_LOCKED.C04 !== 7800 || GOLD_LOCKED.C05A !== 3500) {
    throw new Error('金标 8200/7800/3500 已锁，Cycle 4 不得改数字');
  }
}

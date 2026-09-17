/**
 * Cycle 6 CDP 共用。具名 spec：ops-dashboard-stale-to-calc。
 * 钩子对齐 #33 / Cycle 6 status。缺选择器即红，不得 skip。
 * 查看全部无 stale=1+站月 / 该行停在 ?id= 抽屉 / auto=1 = FAIL。
 * 禁止截图即绿。金标 8200 / 7800 / 3500 已锁。
 * 不新造 XOR / trial-case-gold / trial-equals-calc / 启用闸 / 手工双计 Must 名。
 * 不写产品 UI。不改 FBA。不重写 #9 stale 谓词。不重开 Cycle 4/5 产品句。
 *
 * #33 钩子：
 *   ops-dashboard-stale-to-calc / dashboard-stale-view-all / dashboard-stale-row
 *   （data-period-id）/ period-stale-scope / stale-goto-calculate
 *   落地 period-calc-precheck / period-calc-title / period-calc-start
 * Helper：stalePeriodsViewAllTarget / stalePeriodCalcTarget / periodStaleListParams
 */
import fs from 'node:fs';
import path from 'node:path';

import { GOLD_C03_GROSS, GOLD_C04_GROSS, GOLD_C05A_GROSS } from './cycle2-lib.mjs';
import {
  apiFetch,
  fetchDashboardSummary,
  parseUrl,
  pathOf,
  queryOf,
  requireTestId,
  siteMonth,
  waitPath,
} from './cycle4-lib.mjs';
import { requireHooks } from './cycle5-lib.mjs';

export const GOLD_LOCKED = {
  C03: GOLD_C03_GROSS,
  C04: GOLD_C04_GROSS,
  C05A: GOLD_C05A_GROSS,
};

export const STALE_BLOCK_TITLE = '需重算周期';
export const STALE_SCOPE_COPY = /已按工作台跳转筛选：需重算周期/;
export const LOCKED_GOLD_FORBIDDEN = /4629\.33|预支\s*800/;

export const PR33_DASHBOARD_HOOKS = [
  'ops-dashboard-stale-to-calc',
  'dashboard-stale-view-all',
  'dashboard-stale-row',
];

export const PR33_LANDING_HOOKS = ['period-stale-scope'];

export const PR33_CALC_HOOKS = [
  'period-calc-precheck',
  'period-calc-title',
  'period-calc-start',
];

export const STALE_RECALC_REGRESSION = 'stale-goto-calculate';

export const CYCLE4_DASHBOARD_HOOKS = [
  'ops-dashboard-insight-card-scope',
  'ops-dashboard-abnormal-attention-landing',
  'ops-dashboard-lock-overdue-visible',
];

export const CYCLE5_DASHBOARD_HOOK = 'ops-dashboard-no-plan-to-binding';

const STATUS_PATHS = [
  process.env.CYCLE6_STATUS_FILE,
  process.env.CURSOR_AGENT_STORE
    ? path.join(process.env.CURSOR_AGENT_STORE, 'docs/adversarial-cycle6-implementation-status.md')
    : '',
  '/cursor/stores/bc-2955b371-f65c-4990-a229-d877e2ac6c7a/docs/adversarial-cycle6-implementation-status.md',
].filter(Boolean);

const HOOK_HEADING = /钩子|hooks|FE 对接|CDP hooks/i;
const HOOK_TOKEN = /`((?:cdp|ops|payroll|dashboard|plan|trial|rider|period|stale)-[a-z0-9-]+)`/g;

export {
  apiFetch,
  fetchDashboardSummary,
  parseUrl,
  pathOf,
  queryOf,
  requireHooks,
  requireTestId,
  siteMonth,
  waitPath,
};

export function assertLockedGoldUnchanged() {
  if (GOLD_LOCKED.C03 !== 8200 || GOLD_LOCKED.C04 !== 7800 || GOLD_LOCKED.C05A !== 3500) {
    throw new Error('金标 8200/7800/3500 已锁，Cycle 6 不得改数字');
  }
}

/** #33 stalePeriodsViewAllTarget：stale=1 + 当前站月；无站仍带月。 */
export function stalePeriodsViewAllTarget(siteId, month) {
  const query = { stale: '1' };
  if (siteId != null && Number(siteId) > 0) query.site_id = String(siteId);
  if (month) query.month = month;
  return { path: '/rider-salary/period', query };
}

/** #33 stalePeriodCalcTarget：算薪页。query.id / query.auto 均空。 */
export function stalePeriodCalcTarget(periodId) {
  return {
    path: `/rider-salary/period/${periodId}/calculate`,
    query: {},
  };
}

/** #33 periodStaleListParams：列表请求 stale===true 且带站月。 */
export function periodStaleListParams(siteId, month) {
  const params = { stale: true };
  if (siteId != null && Number(siteId) > 0) params.site_id = Number(siteId);
  if (month) params.month = month;
  return params;
}

export function isPeriodCalculatePath(raw, periodId) {
  const pathname = pathOf(raw);
  const id = periodId ? String(periodId) : '\\d+';
  const re = new RegExp(`/rider-salary/period/${id}/calculate(?:/|\\?|$)`);
  return re.test(pathname) || re.test(String(raw || ''));
}

export function periodIdFromCalcUrl(raw) {
  const match = String(raw || '').match(/\/rider-salary\/period\/(\d+)\/calculate/);
  return match ? match[1] : '';
}

export function isPeriodDrawer(raw) {
  const pathname = pathOf(raw);
  const params = queryOf(raw);
  if (isPeriodCalculatePath(raw)) return false;
  const onList = /\/rider-salary\/period\/?$/.test(pathname);
  return onList && Boolean(params.get('id') || params.get('period_id'));
}

export function isStaleViewAll(raw, { siteId, month } = {}) {
  const pathname = pathOf(raw);
  const params = queryOf(raw);
  if (!/\/rider-salary\/period\/?$/.test(pathname)) return false;
  if (isPeriodCalculatePath(raw) || isPeriodDrawer(raw)) return false;
  const stale = params.get('stale');
  if (stale !== '1' && stale !== 'true') return false;
  if (siteId && params.get('site_id') !== String(siteId)) return false;
  if (!siteId && params.get('site_id')) return false;
  if (month && params.get('month') !== month) return false;
  return true;
}

export function hasAutoCalc(raw) {
  const params = queryOf(raw);
  return params.get('auto') === '1' || params.get('auto') === 'true';
}

export function assertViewAllHasSiteMonth(raw, { siteId, month, label = '需重算查看全部' }) {
  if (isPeriodDrawer(raw)) {
    throw new Error(`${label} 不得落到 /period?id= 抽屉。实际 ${raw}`);
  }
  if (isPeriodCalculatePath(raw)) {
    throw new Error(`${label} 是列表落地，不是单行算薪页。实际 ${raw}`);
  }
  if (hasAutoCalc(raw)) {
    throw new Error(`${label} 禁止 auto=1。实际 ${raw}`);
  }
  if (!isStaleViewAll(raw, { siteId, month })) {
    throw new Error(
      `${label} 须 /period?stale=1 且带当前 site_id+month（无站仍带月）。忽略 query 仍全站 = FAIL。实际 ${raw}`,
    );
  }
}

export function assertRowGoesToCalculate(raw, periodId, label = '需重算该行') {
  if (isPeriodDrawer(raw)) {
    throw new Error(
      `${label} 只开 /period?id= 抽屉、还要再找「去算薪」= FAIL。须 /period/{id}/calculate。实际 ${raw}`,
    );
  }
  if (hasAutoCalc(raw)) {
    throw new Error(`${label} 禁止 auto=1 自动开算。实际 ${raw}`);
  }
  if (!isPeriodCalculatePath(raw, periodId)) {
    throw new Error(`${label} 须进 /rider-salary/period/${periodId}/calculate。实际 ${raw}`);
  }
}

export function assertNoAutoCalc(raw, label = '算薪页') {
  if (hasAutoCalc(raw)) {
    throw new Error(`${label} auto=1 仍禁。实际 ${raw}`);
  }
}

export function assertPeriodListRequestScoped(urls, { siteId, month, label = '周期列表' }) {
  const hits = (urls || []).filter((url) => /\/api\/v1\/rider-salary\/periods(?:\?|$)/.test(url));
  if (!hits.length) {
    throw new Error(`${label} 落地后未见 GET /periods，不得 skip。只切当前页 = FAIL`);
  }
  const ok = hits.some((url) => {
    const q = queryOf(url);
    const stale = q.get('stale') === '1' || q.get('stale') === 'true';
    const siteOk = !siteId || q.get('site_id') === String(siteId);
    const monthOk = !month || q.get('month') === month;
    return stale && siteOk && monthOk;
  });
  if (!ok) {
    throw new Error(
      `${label} 请求必须带 stale=1 与当前 site_id+month。忽略 query 仍全站 = FAIL。实际：${hits.join(' | ')}`,
    );
  }
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

export function readStatusFile() {
  for (const file of STATUS_PATHS) {
    try {
      if (file && fs.existsSync(file)) {
        return { path: file, text: fs.readFileSync(file, 'utf8') };
      }
    } catch {
      /* continue */
    }
  }
  return null;
}

export function loadCycle6StatusHooks() {
  const file = readStatusFile();
  if (!file) return { landed: false, ids: [], path: null };
  const lines = file.text.split(/\r?\n/);
  const ids = new Set();
  let inHookSection = false;
  for (const line of lines) {
    if (/^#{1,3}\s+/.test(line)) {
      inHookSection = HOOK_HEADING.test(line);
    }
    if (!inHookSection) continue;
    HOOK_TOKEN.lastIndex = 0;
    let match = HOOK_TOKEN.exec(line);
    while (match) {
      ids.add(match[1]);
      match = HOOK_TOKEN.exec(line);
    }
  }
  return { landed: ids.size > 0, ids: [...ids], path: file.path };
}

export async function expandNeedRecalcPanel(page) {
  const row = page.getByTestId('dashboard-stale-row').first();
  const viewAll = page.getByTestId('dashboard-stale-view-all').first();
  const recalc = page.getByTestId(STALE_RECALC_REGRESSION).first();
  if ((await row.isVisible().catch(() => false)) || (await viewAll.isVisible().catch(() => false))) {
    return;
  }
  if (await recalc.isVisible().catch(() => false)) return;

  const header = page
    .locator('.ant-collapse-header')
    .filter({ hasText: STALE_BLOCK_TITLE })
    .first();
  const headerByRole = page.getByRole('button', { name: /需重算周期/ });
  try {
    if (await header.count()) {
      await header.waitFor({ state: 'visible', timeout: 20000 });
      await header.click();
    } else if (await headerByRole.count()) {
      await headerByRole.first().waitFor({ state: 'visible', timeout: 20000 });
      await headerByRole.first().click();
    } else {
      await page.getByText(STALE_BLOCK_TITLE, { exact: true }).first().click();
    }
  } catch (err) {
    throw new Error(
      `未找到工作台「${STALE_BLOCK_TITLE}」折叠头，不得 skip。请确认夹具有本站 stale 周期。` +
        ` 原始错误：${err.message}`,
    );
  }
}

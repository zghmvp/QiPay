/**
 * Cycle 5 CDP 共用。钩子读 status 文件（落地才强制 testid）；未落地则只断言计划合同。
 * 禁止截图即绿；选择器/文案/落地缺失即失败，不得 skip。
 * 金标 8200 / 7800 / 3500 已锁。不新造 XOR / trial-case-gold / 启用闸 Must 名。
 * 不写产品 UI。侧栏泄漏不改断言。
 *
 * 具名：cdp-admin-payslip-hide-empty-days /
 *   ops-dashboard-no-plan-to-binding /
 *   ops-plan-manual-not-double（可挂现有方案保存 spec，不新造 XOR/金标/启用闸名）
 */
import fs from 'node:fs';
import path from 'node:path';

import { apiFetch, siteMonth } from './cycle1-lib.mjs';
import { GOLD_C03_GROSS, GOLD_C04_GROSS, GOLD_C05A_GROSS } from './cycle2-lib.mjs';
import { fetchDashboardSummary, requireTestId } from './cycle4-lib.mjs';

export const GOLD_LOCKED = {
  C03: GOLD_C03_GROSS,
  C04: GOLD_C04_GROSS,
  C05A: GOLD_C05A_GROSS,
};

export const MANUAL_BONUS_FIELD = '本期手工奖';
export const MANUAL_PENALTY_FIELD = '本期手工惩';
export const MANUAL_FIELDS = [MANUAL_BONUS_FIELD, MANUAL_PENALTY_FIELD];
export const MANUAL_ONCE_AMOUNT = 200;

export const SHOW_EMPTY_DAYS_COPY = /显示空日\s*[（(]\s*\d+\s*[)）]|显示空日/;
export const DAILY_NET_COPY = /当日公式\s*[+＋]\s*奖\s*[−\-–-]\s*惩/;
export const DAILY_NET_NOT_PERIOD_COPY = /不是周期实发/;
export const EMPTY_CALENDAR_COPY = /请选择站点和骑手/;
export const MANUAL_BOOKED_COPY = /手工明细已入账/;
export const MANUAL_DOUBLE_COPY = /再加会双计/;
export const MANUAL_ASSEMBLER_COPY = /可作条件/;
export const MANUAL_ASSEMBLER_DOUBLE_COPY = /加进公式\s*=\s*双计/;
export const BINDING_TAB_COPY = /方案绑定/;
export const BINDING_CREATE_COPY = /新增绑定|保存绑定/;
export const LOCKED_GOLD_FORBIDDEN = /4629\.33|预支\s*800/;

const STATUS_PATHS = [
  process.env.CYCLE5_STATUS_FILE,
  process.env.CURSOR_AGENT_STORE
    ? path.join(process.env.CURSOR_AGENT_STORE, 'docs/adversarial-cycle5-implementation-status.md')
    : '',
  '/cursor/stores/bc-2955b371-f65c-4990-a229-d877e2ac6c7a/docs/adversarial-cycle5-implementation-status.md',
].filter(Boolean);

const HOOK_HEADING = /钩子|hooks|FE 对接|CDP hooks/i;
const HOOK_TOKEN = /`((?:cdp|ops|payroll|dashboard|plan|trial|rider|period)-[a-z0-9-]+)`/g;

export {
  apiFetch,
  fetchDashboardSummary,
  requireTestId,
  siteMonth,
};

export function assertLockedGoldUnchanged() {
  if (GOLD_LOCKED.C03 !== 8200 || GOLD_LOCKED.C04 !== 7800 || GOLD_LOCKED.C05A !== 3500) {
    throw new Error('金标 8200/7800/3500 已锁，Cycle 5 不得改数字');
  }
}

export function moneyOf(value) {
  const n = Number(String(value ?? '').replace(/,/g, ''));
  return Number.isFinite(n) ? Math.round(n * 100) / 100 : 0;
}

export function bizDateOf(value) {
  return String(value ?? '').slice(0, 10);
}

export function flattenPayrollDetails(detail) {
  const grouped = detail?.details || {};
  return Object.values(grouped).flat();
}

export function dayHasAdvance(day, details) {
  const date = bizDateOf(day.biz_date);
  return (details || []).some(
    (row) => row.source === 'advance' && bizDateOf(row.biz_date) === date,
  );
}

export function dayHasGrossBonus(day, details) {
  if (moneyOf(day.manual_bonus) !== 0) return true;
  const date = bizDateOf(day.biz_date);
  return (details || []).some((row) => {
    if (bizDateOf(row.biz_date) !== date) return false;
    if (row.include_in_gross !== true) return false;
    return moneyOf(row.amount) > 0 && (row.direction === 'bonus' || row.source === 'manual');
  });
}

export function dayHasOffGrossPenalty(day, details) {
  if (moneyOf(day.manual_penalty) !== 0) return true;
  const date = bizDateOf(day.biz_date);
  return (details || []).some((row) => {
    if (bizDateOf(row.biz_date) !== date) return false;
    return row.include_in_gross === false && row.direction === 'penalty' && moneyOf(row.amount) !== 0;
  });
}

export function isAlwaysVisibleDaily(day, details) {
  const orders = Number(day.order_count || 0);
  const valid = Number(day.valid_order_count || 0);
  if (day.day_status === 'no_plan' && (valid > 0 || orders > 0)) return true;
  if (dayHasGrossBonus(day, details)) return true;
  if (dayHasOffGrossPenalty(day, details)) return true;
  if (dayHasAdvance(day, details)) return true;
  return false;
}

export function isDefaultHiddenEmptyDaily(day, details) {
  if (isAlwaysVisibleDaily(day, details)) return false;
  const orders = Number(day.order_count || 0);
  const valid = Number(day.valid_order_count || 0);
  const noAmount = moneyOf(day.formula_amount) === 0 && moneyOf(day.net_adjust) === 0;
  const noManual = moneyOf(day.manual_bonus) === 0 && moneyOf(day.manual_penalty) === 0;
  const noAdvance = !dayHasAdvance(day, details);
  if (!noManual || !noAdvance) return false;
  if (day.day_status === 'not_imported') return true;
  return orders === 0 && valid === 0 && noAmount;
}

export function classifyDailies(detail) {
  const details = flattenPayrollDetails(detail);
  const dailies = detail?.dailies || [];
  return {
    details,
    dailies,
    hidden: dailies.filter((row) => isDefaultHiddenEmptyDaily(row, details)),
    visible: dailies.filter((row) => !isDefaultHiddenEmptyDaily(row, details)),
  };
}

export function parseUrl(raw, base = 'http://127.0.0.1') {
  try {
    return new URL(raw, base);
  } catch {
    return null;
  }
}

export function pathOf(raw, base = 'http://127.0.0.1') {
  const url = parseUrl(raw, base);
  return url ? url.pathname : String(raw || '');
}

export function queryOf(raw, base = 'http://127.0.0.1') {
  const url = parseUrl(raw, base);
  return url ? url.searchParams : new URLSearchParams();
}

export function isCalendarPath(raw) {
  return /\/rider-salary\/calendar(?:\/|$)/.test(pathOf(raw));
}

export function isBindingLanding(raw, riderId) {
  const url = parseUrl(raw);
  if (!url) return false;
  const path = url.pathname;
  const tab = url.searchParams.get('tab');
  if (tab !== 'binding') return false;
  const detail = path.match(/\/rider-salary\/rider\/(\d+)/);
  if (detail) {
    return !riderId || String(detail[1]) === String(riderId);
  }
  if (/\/rider-salary\/rider\/?$/.test(path)) {
    const queryId = url.searchParams.get('rider_id');
    return Boolean(queryId) && (!riderId || String(queryId) === String(riderId));
  }
  return false;
}

export function assertRowGoesToBinding(raw, riderId, label = '无方案日行') {
  if (isCalendarPath(raw)) {
    throw new Error(
      `${label} 只进 /calendar（即使带 rider_id+site_id+month）= FAIL。须落到档案绑定时间轴。实际 ${raw}`,
    );
  }
  if (!isBindingLanding(raw, riderId)) {
    throw new Error(
      `${label} 须进 /rider/{id}?tab=binding（或带 rider_id+tab=binding 的等价落地）。实际 ${raw}`,
    );
  }
}

export function assertViewAllNotEmptyCalendar(raw, bodyText, label = '无方案日查看全部') {
  const text = String(bodyText || '');
  if (EMPTY_CALENDAR_COPY.test(text) && isCalendarPath(raw)) {
    throw new Error(`${label} 不得落到「请选择站点和骑手」空日历。实际 ${raw}`);
  }
  if (isCalendarPath(raw)) {
    throw new Error(
      `${label} 不得进 /calendar。允许骑手名单/档案筛，每行再进绑定。实际 ${raw}`,
    );
  }
}

function prevNonSpace(expr, index) {
  return String(expr || '')
    .slice(0, index)
    .replace(/\s+$/g, '');
}

export function fieldUsedAsAddend(expr, field) {
  const raw = String(expr || '').replace(/[−–]/g, '-');
  if (!raw.includes(field)) return false;
  let from = 0;
  while (from < raw.length) {
    const index = raw.indexOf(field, from);
    if (index < 0) break;
    const prev = prevNonSpace(raw, index);
    if (!prev.endsWith('-')) return true;
    from = index + field.length;
  }
  return false;
}

export function isManualAddendFormula(formula) {
  if (!formula || typeof formula !== 'object') return false;
  const kind = formula.类型;
  const field = String(formula.字段 || '');
  if (MANUAL_FIELDS.includes(field) && kind !== '表达式') return true;
  if (kind === '固定金额' && MANUAL_FIELDS.some((name) => JSON.stringify(formula.金额 || '').includes(name))) {
    return true;
  }
  if (kind === '表达式' || formula.表达式) {
    const expr = String(formula.表达式 || '');
    return MANUAL_FIELDS.some((name) => fieldUsedAsAddend(expr, name));
  }
  return MANUAL_FIELDS.some((name) => fieldUsedAsAddend(JSON.stringify(formula), name) && kind !== '表达式');
}

export function isManualConditionOnly(condition) {
  const blob = JSON.stringify(condition || {});
  return MANUAL_FIELDS.some((name) => blob.includes(name));
}

export function failBlob(res, json) {
  return `${json?.msg || ''} ${JSON.stringify(json || {})} HTTP ${res?.status}`;
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

export function loadCycle5StatusHooks() {
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

export async function requireStatusHooks(page, extraMessage) {
  const hooks = loadCycle5StatusHooks();
  for (const testId of hooks.ids) {
    await requireTestId(
      page,
      testId,
      extraMessage || `未见 status 钩子 ${testId}，不得 skip`,
    );
  }
  return hooks;
}

export async function requirePlanCopy(page, pattern, message) {
  const body = await page.locator('body').innerText();
  if (!pattern.test(body)) {
    throw new Error(message || `未见计划合同文案 ${pattern}，不得 skip`);
  }
  return body;
}

export async function visibleDailyDates(page) {
  const tab = page.getByTestId('payroll-detail-tabs');
  const scope = (await tab.count()) ? tab : page.locator('body');
  const texts = await scope.locator('a, td, th, span, div').allInnerTexts();
  return [...new Set(texts.map((text) => (String(text).match(/\d{4}-\d{2}-\d{2}/) || [])[0]).filter(Boolean))];
}

export async function waitPath(page, re, timeout = 15000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (re.test(page.url())) return page.url();
    await page.waitForTimeout(150);
  }
  throw new Error(`未跳到 ${re}，实际 ${page.url()}`);
}

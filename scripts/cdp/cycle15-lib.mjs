/**
 * Cycle 15 CDP 共用。具名五席，不得扩第六句。
 * 钩子缺失即红，不得 skip。禁止截图即绿。
 * Must 2 必须走订单抽屉纠错或补录，禁止 API 绿替。
 * Must 3 必须走反冲确认框 + 成功后该期算薪页，禁止只断言文案。
 * Must 4 必须走批量模态 + 半填行，禁止写成整批 422。
 * Must 5 不验收 Cycle 13 芯片 / 查看周期；不验收 Cycle 14 已算日「周期项不落日 / 对账看条」。
 * 金标 8200 / 7800 / 3500 已锁。不改 trial-case-gold 产品句。
 * 不写产品 UI。不改 FBA。不改决策 29。不改离职计数谓词。不改 attention 谓词。
 * 不改奖惩入账谓词。不改 XOR。不改金标三数。
 */
export const GOLD_C03_GROSS = 8200;
export const GOLD_C04_GROSS = 7800;
export const GOLD_C05A_GROSS = 3500;

export const GOLD_LOCKED = {
  C03: GOLD_C03_GROSS,
  C04: GOLD_C04_GROSS,
  C05A: GOLD_C05A_GROSS,
};

export const LOCKED_GOLD_FORBIDDEN = /4629\.33|预支\s*800/;

export const RESIGNED_BLOCK_TITLE = '离职仍有本月订单';
export const STALE_COPY = /需重算|未出账/;
export const FIX_ONLY_TOAST = /已纠错订单|已补录订单/;
export const BATCH_ALL_SUCCESS_COPY = /批量录入成功/;
export const UNCALCULATED_COPY = /未算薪|尚未算薪/;
export const ORDER_NOT_IN_CALC_COPY = /未进本次算薪|尚未进本次算薪|尚未算薪/;
export const WITHHOLD_HINT_COPY = /代扣不进日手工/;
export const CYCLE14_CALCULATED_DAY_COPY = /周期项不落日/;
export const ZERO_MONEY = /(?:^|[^\d])0\.00(?:[^\d]|$)/;
export const EMPTY_AMOUNT = /—|－|未算薪|尚未算薪/;
export const FORMULA_AMOUNT_LABEL = '公式金额';
export const NET_AMOUNT_LABEL = '净额';
export const COVERING_STATUSES = new Set(['open', 'reopened']);

export const MUST1_HOOKS = [
  'ops-resigned-order-deeplink',
  'dashboard-resigned-row',
  'dashboard-resigned-view-all',
];

export const MUST1_LANDING_HOOKS = [
  'rider-profile-open',
  'order-rider-month-scope',
  'rider-row-active',
];

export const MUST1_VIEW_ALL_HOOKS = ['rider-list-resigned-scope'];

export const MUST2_DRAWER_HOOKS = [
  'ops-order-fix-shows-stale',
  'order-form-drawer',
];

export const MUST2_SUCCESS_HOOKS = [
  'order-fix-stale-copy',
  'order-fix-goto-calc',
];

export const MUST3_CONFIRM_HOOKS = [
  'ops-reverse-confirm-then-calc',
  'period-reverse-confirm',
  'period-reverse-count',
  'period-reverse-rider-count',
];

export const MUST3_LANDING_HOOKS = ['period-calc-title'];

export const MUST4_MODAL_HOOKS = [
  'ops-adj-batch-skip-incomplete-not-all-success',
  'adj-batch-modal',
];

export const MUST4_RESULT_HOOKS = [
  'adj-batch-created-count',
  'adj-batch-skipped-count',
];

export const MUST4_INCOMPLETE_HOOKS = ['adj-batch-incomplete-row'];

export const MUST5_HOOKS = [
  'cdp-admin-day-uncalculated-not-zero',
  'day-drawer-formula-amount',
  'day-drawer-net',
  'day-drawer-uncalculated',
];

export const MUST5_ORDER_HOOKS = ['day-drawer-order-not-in-calc'];

export const NAMED_SPECS = [
  'ops-resigned-order-deeplink',
  'ops-order-fix-shows-stale',
  'ops-reverse-confirm-then-calc',
  'ops-adj-batch-skip-incomplete-not-all-success',
  'cdp-admin-day-uncalculated-not-zero',
];

export const FIXTURE_RESIGNED_RIDER_ID = 151001;
export const FIXTURE_RESIGNED_JOB = 'D5A015';
export const FIXTURE_RESIGNED_NAME = '夹具离职骑手';
export const FIXTURE_ORDER_ID = 151002;
export const FIXTURE_PERIOD_ID = 151003;
export const FIXTURE_DAY = '2026-09-16';
export const FIXTURE_BATCH_CREATED = 2;
export const FIXTURE_BATCH_SKIPPED = 1;

export function assertLockedGoldUnchanged() {
  if (
    GOLD_LOCKED.C03 !== 8200 ||
    GOLD_LOCKED.C04 !== 7800 ||
    GOLD_LOCKED.C05A !== 3500
  ) {
    throw new Error('金标 8200/7800/3500 已锁，Cycle 15 不得改数字');
  }
}

export function assertNoOrderApiGreen() {
  if (
    typeof globalThis.updateOrderApi === 'function' ||
    typeof globalThis.createOrderApi === 'function'
  ) {
    throw new Error('本席禁止走 updateOrderApi / createOrderApi。API 绿替抽屉 = FAIL');
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

export function monthFromDate(bizDate) {
  const text = String(bizDate || '');
  return text.length >= 7 ? text.slice(0, 7) : '';
}

export function isResignedRowLanding(raw, { riderId, month } = {}) {
  const pathname = pathOf(raw);
  const params = queryOf(raw);
  if (!riderId) return false;
  const profile = pathname.match(/\/rider-salary\/rider\/(\d+)(?:\/|$)/);
  if (profile && String(profile[1]) === String(riderId)) return true;
  if (
    /\/rider-salary\/order(?:\/|$)/.test(pathname) &&
    params.get('rider_id') === String(riderId)
  ) {
    if (!month) return true;
    const from = params.get('date_from') || params.get('month') || '';
    return from.startsWith(month) || params.get('month') === month;
  }
  return false;
}

export function isResignedListWithoutThisRider(raw, riderId) {
  const pathname = pathOf(raw);
  const params = queryOf(raw);
  if (!/\/rider-salary\/rider\/?$/.test(pathname)) return false;
  if (params.get('status') !== 'resigned') return false;
  const opened = params.get('rider_id') || params.get('id') || params.get('edit_id');
  return !opened || String(opened) !== String(riderId);
}

export function isSiteWideOrdersWithoutRiderOrMonth(raw, { riderId, month } = {}) {
  const pathname = pathOf(raw);
  const params = queryOf(raw);
  if (!/\/rider-salary\/order(?:\/|$)/.test(pathname)) return false;
  if (params.get('rider_id') === String(riderId)) return false;
  if (month) {
    const from = params.get('date_from') || params.get('month') || '';
    if (from.startsWith(month) || params.get('month') === month) {
      return params.get('rider_id') !== String(riderId);
    }
  }
  return true;
}

export function isResignedViewAll(raw, { siteId, month } = {}) {
  const pathname = pathOf(raw);
  const params = queryOf(raw);
  if (!/\/rider-salary\/rider\/?$/.test(pathname)) return false;
  if (params.get('status') !== 'resigned') return false;
  if (siteId != null && params.get('site_id') !== String(siteId)) return false;
  if (month && params.get('month') !== month) return false;
  return true;
}

export function isCoveringCalcLanding(raw, periodId) {
  const pathname = pathOf(raw);
  return (
    String(landingPeriodId(raw)) === String(periodId) &&
    /\/rider-salary\/period\/\d+\/calculate/.test(pathname)
  );
}

export function isPeriodListWithMonth(raw, { siteId, month } = {}) {
  const pathname = pathOf(raw);
  const params = queryOf(raw);
  if (!/\/rider-salary\/period\/?$/.test(pathname)) return false;
  if (/\/calculate(?:\/|$)/.test(pathname)) return false;
  if (siteId != null && params.get('site_id') !== String(siteId)) return false;
  if (month && params.get('month') !== month) return false;
  return true;
}

export function isPeriodListWithoutThisCalc(raw, periodId) {
  const pathname = pathOf(raw);
  if (!/\/rider-salary\/period\/?$/.test(pathname)) return false;
  if (/\/calculate(?:\/|$)/.test(pathname)) return false;
  const landed = landingPeriodId(raw);
  return !landed || String(landed) !== String(periodId);
}

export function coveringPeriodIsOpen(status) {
  return COVERING_STATUSES.has(String(status || ''));
}

export function isStaleFixCopy(text) {
  return STALE_COPY.test(String(text || ''));
}

export function isFixOnlyToast(text) {
  const blob = String(text || '');
  return FIX_ONLY_TOAST.test(blob) && !STALE_COPY.test(blob);
}

export function isReverseConfirmScope(text, { reversalCount, riderCount } = {}) {
  const blob = String(text || '');
  if (!/\d/.test(blob)) return false;
  if (reversalCount != null && !blob.includes(String(reversalCount))) return false;
  if (riderCount != null && !blob.includes(String(riderCount))) return false;
  return /反冲/.test(blob) && /人/.test(blob);
}

export function isBatchHalfSuccessCopy(text, { created, skipped } = {}) {
  const blob = String(text || '');
  if (Number(skipped) > 0 && BATCH_ALL_SUCCESS_COPY.test(blob) && !/跳过/.test(blob)) {
    return false;
  }
  if (created != null && !blob.includes(String(created))) return false;
  if (skipped != null && Number(skipped) > 0 && !blob.includes(String(skipped))) {
    return false;
  }
  return /跳过|未完整/.test(blob) || Number(skipped) === 0;
}

export function isUncalculatedEmptyAmount(text) {
  const blob = String(text || '');
  if (UNCALCULATED_COPY.test(blob)) return true;
  if (EMPTY_AMOUNT.test(blob) && !/今日\s*0/.test(blob)) return true;
  return false;
}

export function isBareZeroWithoutUncalculated(text) {
  const blob = String(text || '');
  return ZERO_MONEY.test(blob) && !UNCALCULATED_COPY.test(blob) && !EMPTY_AMOUNT.test(blob);
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
      extraMessage || `未见 Cycle 15 钩子 ${testId}，不得 skip`,
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

export async function fetchOrders(apiUrl, token, params = {}) {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value != null && value !== '') qs.set(key, String(value));
  }
  const { res, json } = await apiFetch(
    apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/orders?${qs}`,
  );
  if (!res.ok) {
    throw new Error(`订单列表 HTTP ${res.status}，不得 skip`);
  }
  return json?.data || json;
}

export async function fetchPeriodForDate(apiUrl, token, { siteId, date, riderId }) {
  const qs = new URLSearchParams({ site_id: String(siteId), date: String(date) });
  if (riderId) qs.set('rider_id', String(riderId));
  const { res, json } = await apiFetch(
    apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/periods/for-date?${qs}`,
  );
  if ([404, 405, 501].includes(res.status)) {
    throw new Error(`覆盖期查询缺失 HTTP ${res.status}，不得 skip`);
  }
  return json?.data || json;
}

export async function fetchPeriods(apiUrl, token, params = {}) {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value != null && value !== '') qs.set(key, String(value));
  }
  const { res, json } = await apiFetch(
    apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/periods?${qs}`,
  );
  if (!res.ok) {
    throw new Error(`周期列表 HTTP ${res.status}，不得 skip`);
  }
  return json?.data || json;
}

export async function fetchReversePreflight(apiUrl, token, periodId) {
  const paths = [
    `/api/v1/rider-salary/periods/${periodId}/reverse-preflight`,
    `/api/v1/rider-salary/periods/${periodId}/reverse/preflight`,
  ];
  let last = null;
  for (const urlPath of paths) {
    last = await apiFetch(apiUrl, token, 'GET', urlPath);
    if (last.res.ok) return last.json?.data || last.json;
    if (![404, 405, 501].includes(last.res.status)) {
      throw new Error(
        `反冲预检 HTTP ${last.res.status}：${JSON.stringify(last.json).slice(0, 300)}`,
      );
    }
  }
  throw new Error(
    `反冲预检缺失（须 reverse_preflight 给出 reversal_count + 涉及骑手数）。前端抄列表 rider_count = FAIL。最后 ${last?.res?.status}`,
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

export async function clickRowAction(page, row, name) {
  const btn = row.getByText(name, { exact: true });
  if (await btn.count()) {
    await btn.first().click();
    return;
  }
  const more = row.getByText(/更多|更多操作/);
  if (await more.count()) {
    await more.first().click();
    await page.getByRole('menuitem', { name: new RegExp(`^${name}$`) }).click();
    return;
  }
  throw new Error(`未见行操作「${name}」，不得 skip`);
}

export async function confirmVisibleDialog(page, nameRe = /确认|确定|继续/) {
  const btn = page.getByRole('button', { name: nameRe }).last();
  await btn.waitFor({ state: 'visible', timeout: 15000 });
  await btn.click();
}

export function assertResignedRowOpensThis(raw, { riderId, month, riderName }) {
  if (isResignedListWithoutThisRider(raw, riderId)) {
    throw new Error(
      `离职行进了离职总名单且无该人打开（rider_id=${riderId}）。本席 FAIL。实际 ${raw}`,
    );
  }
  if (isSiteWideOrdersWithoutRiderOrMonth(raw, { riderId, month })) {
    throw new Error(
      `离职行进了整站订单却无该骑手/无该月。须档案或该骑手本月订单。实际 ${raw}`,
    );
  }
  if (!isResignedRowLanding(raw, { riderId, month })) {
    throw new Error(
      `点离职行须进该骑手档案或该骑手本月订单（rider_id=${riderId}${riderName ? ` ${riderName}` : ''}）。点行无反应 / 不带 rider_id / 落到别人 = FAIL。实际 ${raw}`,
    );
  }
}

export function assertResignedViewAllScoped(raw, { siteId, month }) {
  if (!isResignedViewAll(raw, { siteId, month })) {
    throw new Error(
      `查看全部须继续吃 status=resigned + 当前站月。改离职谓词 / 并进 attention=1 = FAIL。实际 ${raw}`,
    );
  }
  if (/[?&]attention=1(?:&|$)/.test(raw)) {
    throw new Error('离职查看全部不得并进 attention=1。改谓词 = 本席 FAIL');
  }
}

export function assertFixShowsStale(text) {
  const blob = String(text || '');
  if (isFixOnlyToast(blob)) {
    throw new Error(
      '只 toast「已纠错订单 / 已补录订单」且无「需重算 / 未出账」= FAIL。只改 toast 人还停在订单抽屉 = 本席仍 FAIL',
    );
  }
  if (!isStaleFixCopy(blob)) {
    throw new Error(
      `纠错/补录成功反馈必须写出需重算 / 未出账。主文案把写订单读成薪资已更新 = FAIL。实际：${blob.slice(0, 300)}`,
    );
  }
  if (/薪资已更新|已出账|已入账/.test(blob) && !STALE_COPY.test(blob)) {
    throw new Error('主文案把写订单读成薪资已更新 = FAIL');
  }
}

export function assertFixGotoCoveringCalc(raw, covering) {
  if (covering?.period?.id && coveringPeriodIsOpen(covering.period.status)) {
    if (!isCoveringCalcLanding(raw, covering.period.id)) {
      throw new Error(
        `有覆盖期时主 CTA 须进该期算薪页 period_id=${covering.period.id}。落到错站/错期/周期列表自己猜 = FAIL。实际 ${raw}`,
      );
    }
    return;
  }
  const siteId = covering?.site_id;
  const month = monthFromDate(covering?.start_date || covering?.period?.start_date);
  if (!isPeriodListWithMonth(raw, { siteId, month })) {
    throw new Error(
      `找不到覆盖期时须落到该站周期列表带月，并仍写出需重算。不得假装已出账。实际 ${raw}`,
    );
  }
}

export function assertReverseConfirmThenCalc(raw, periodId) {
  if (!isCoveringCalcLanding(raw, periodId)) {
    throw new Error(
      `反冲确认成功后必须进入该 period_id=${periodId} 算薪页。停在周期列表且无该期算薪入口 = FAIL。只改确认文案不算交付。实际 ${raw}`,
    );
  }
}

export function assertReverseConfirmCounts(text, preflight, listRiderCount) {
  const blob = String(text || '');
  const reversalCount = preflight?.reversal_count;
  const riderCount = preflight?.rider_count ?? preflight?.involved_rider_count;
  if (reversalCount == null || riderCount == null) {
    throw new Error('反冲确认须吃后端预检 reversal_count + 涉及骑手数。钩子缺失即红，不得 skip');
  }
  if (!blob.includes(String(reversalCount)) || !blob.includes(String(riderCount))) {
    throw new Error(
      `只有套话且无单数/人数 = FAIL。期望反冲 ${reversalCount} / 骑手 ${riderCount}。实际：${blob.slice(0, 300)}`,
    );
  }
  if (
    listRiderCount != null &&
    Number(listRiderCount) !== Number(riderCount) &&
    blob.includes(String(listRiderCount)) &&
    !blob.includes(String(riderCount))
  ) {
    throw new Error(
      '人数=窗内有单全量而实际只反冲本周期已定稿条 = FAIL。前端不得抄列表 rider_count',
    );
  }
}

export function assertBatchSkipIncomplete(text, { created, skipped }) {
  const blob = String(text || '');
  if (Number(skipped) >= 1 && BATCH_ALL_SUCCESS_COPY.test(blob) && !/跳过/.test(blob)) {
    throw new Error(
      `存在半填行仍只 toast「批量录入成功」、不出现跳过 M = FAIL。实际：${blob.slice(0, 300)}`,
    );
  }
  if (!isBatchHalfSuccessCopy(blob, { created, skipped })) {
    throw new Error(
      `批量奖惩半填必须同时看得见已录入 ${created} 与跳过未完整 ${skipped}。主文案把部分行入库读成整表已录入 = FAIL。实际：${blob.slice(0, 300)}`,
    );
  }
}

export function assertDayUncalculatedNotZero({ drawerText, formulaText, netText, orderText }) {
  const drawer = String(drawerText || '');
  const formula = String(formulaText || '');
  const net = String(netText || '');
  const order = String(orderText || '');
  if (!drawer.includes(FORMULA_AMOUNT_LABEL) || !drawer.includes(NET_AMOUNT_LABEL)) {
    throw new Error(`日抽屉五卡须能读出「公式金额 / 净额」。实际：${drawer.slice(0, 200)}`);
  }
  if (isBareZeroWithoutUncalculated(`${formula}\n${net}\n${drawer}`)) {
    throw new Error(
      '有完成单、无 daily cache 时五卡主数字是 0.00 且无「未算薪」类中文 = FAIL。须「—」或等价空态，不能让站长指着 0 说这天没提成',
    );
  }
  if (!isUncalculatedEmptyAmount(`${formula}\n${net}\n${drawer}`)) {
    throw new Error(
      `公式金额 / 净额必须能读出「未算薪，不是今日提成为 0」。实际公式：${formula.slice(0, 80)} 净额：${net.slice(0, 80)}`,
    );
  }
  if (order && /无命中项/.test(order) && !ORDER_NOT_IN_CALC_COPY.test(order)) {
    throw new Error(
      '同日订单展开只写「无命中项」、无「未进本次算薪 / 尚未算薪」= FAIL',
    );
  }
  if (CYCLE14_CALCULATED_DAY_COPY.test(drawer) && !UNCALCULATED_COPY.test(drawer)) {
    throw new Error(
      '本席不验收 Cycle 14 已算日「周期项不落日」。把本席写成那句 = 本席废。须写未算薪空态',
    );
  }
  if (LOCKED_GOLD_FORBIDDEN.test(drawer)) {
    throw new Error('金标 8200/7800/3500 已锁，不得出现 4629.33 / 预支 800');
  }
}

export function assertWithholdNotInDailyManual(text, { hasWithhold } = {}) {
  if (!hasWithhold) return;
  if (!WITHHOLD_HINT_COPY.test(String(text || ''))) {
    throw new Error(
      '同日无 cache 时，把 include_in_gross=false 代扣加进「手工惩 / 净额」且无「代扣不进日手工」= FAIL',
    );
  }
}

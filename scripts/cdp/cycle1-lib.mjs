/**
 * Cycle 1 CDP 共用：鉴权、夹具、假完成「完成」语义。
 * 禁止截图 / 向导连通 / CDP_ALLOW_EMPTY_STALE 换绿。
 *
 * 叠 PR #14 + #16。latest 不得当缺失 skip：
 *   GET /recalc-jobs/latest?site_id= → 200 + { site_id, job }（job 可空，不 404）
 *   GET /orders?missing_delivery=1 须真正过滤
 *   POST /periods/{id}/lock 硬失败优先于 stale
 * 前端关向导入口走 latest；localStorage 仅接口失败回退。
 */
export const FIX_JOB_NO = 'FIX_C17_R1';
export const LOCK_JOB_NO = 'FIX_C17_LOCK';
export const MISS_ORDER_NO = 'FIX_C17_MISSDEL_20260910';
export const MISS_ORDER_DAY = '2026-09-10';
export const NO_PLAN_DAY = '2026-09-15';

export const HARD_FAIL_COPY = /锁账中止|无生效方案|未算出|缺送达|送达时间为空|从未成功/;
export const STALE_COPY = /存在需重算的薪资结果|请先重算/;
export const PARTIAL_FAIL_COPY = /部分失败|失败\s*\d+\s*人/;
export const GREEN_COMPLETE_COPY = /重算状态：完成(?!前)|完成：已重算/;
export const STILL_LOCK_COPY = /仍要锁/;
export const IMPORT_NOT_PAYROLL_COPY = /导入完成\s*≠\s*已出账/;

export function authHeaders(token, extra = {}) {
  return { Authorization: `Bearer ${token}`, ...extra };
}

export function isApiAbsent(res, json) {
  if ([404, 405, 501].includes(res.status)) return true;
  const blob = `${json?.msg || ''} ${json?.detail || ''} ${JSON.stringify(json || {})}`;
  return /Not Found|Method Not Allowed|未实现|不存在该接口/i.test(blob) && res.status >= 400;
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

export async function resolveFixRiderId(apiUrl, token, siteId) {
  if (process.env.CDP_RIDER_ID) return String(process.env.CDP_RIDER_ID);
  const qs = new URLSearchParams({
    page: '1',
    size: '20',
    site_id: String(siteId),
    keyword: FIX_JOB_NO,
  });
  const { res, json } = await apiFetch(
    apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/riders?${qs}`,
  );
  if (!res.ok) throw new Error(`查找 ${FIX_JOB_NO} 失败：HTTP ${res.status}`);
  const hit = (json?.data?.items || []).find((r) => r.job_no === FIX_JOB_NO);
  if (!hit) {
    throw new Error(`未找到工号 ${FIX_JOB_NO}。请先运行 node scripts/cdp/seed-xiaoxiang-fixtures.mjs`);
  }
  return String(hit.id);
}

export function assertNotGreenCompleteAlone(text, { job } = {}) {
  const blob = `${text || ''} ${job?.message || ''} ${JSON.stringify(job || {})}`;
  const failedCount = Number(
    job?.failed_rider_count ?? job?.payload?.failed_rider_count ?? 0,
  );
  const jobFailed =
    job?.status === 'failed' || failedCount > 0 || PARTIAL_FAIL_COPY.test(blob);
  if (/重算状态：完成/.test(blob) && !jobFailed && !PARTIAL_FAIL_COPY.test(blob)) {
    throw new Error(`夹具含无方案有单骑手时不得纯绿「完成」：${blob.slice(0, 400)}`);
  }
  if (job && job.status === 'done' && failedCount === 0 && !PARTIAL_FAIL_COPY.test(blob)) {
    throw new Error(
      `重算 job 以完成收场且失败人数为 0。夹具须含 ${FIX_JOB_NO}：${blob.slice(0, 400)}`,
    );
  }
}

export function assertPartialFailVisible(text, job) {
  const blob = `${text || ''} ${job?.message || ''} ${JSON.stringify(job?.payload || {})}`;
  const failedCount = Number(
    job?.failed_rider_count ?? job?.payload?.failed_rider_count ?? 0,
  );
  if (!PARTIAL_FAIL_COPY.test(blob) && failedCount <= 0 && job?.status !== 'failed') {
    throw new Error(`未见部分失败文案或失败人数（夹具 ${FIX_JOB_NO}）：${blob.slice(0, 400)}`);
  }
}

export function assertNoStillLock(text) {
  if (STILL_LOCK_COPY.test(text || '')) {
    throw new Error('锁账路径出现「仍要锁」软通道');
  }
}

export async function waitRecalcJob(apiUrl, token, jobId, { timeoutMs = 180000 } = {}) {
  const started = Date.now();
  let last = null;
  while (Date.now() - started < timeoutMs) {
    const { res, json } = await apiFetch(
      apiUrl,
      token,
      'GET',
      `/api/v1/rider-salary/recalc-jobs/${jobId}`,
    );
    if (!res.ok) {
      throw new Error(`读取重算任务 ${jobId} 失败：HTTP ${res.status} ${JSON.stringify(json).slice(0, 200)}`);
    }
    last = json?.data;
    if (last?.status === 'done' || last?.status === 'failed') return last;
    await new Promise((r) => setTimeout(r, 1500));
  }
  throw new Error(`等待重算任务 ${jobId} 超时（${timeoutMs}ms）最后状态=${last?.status}`);
}

export function buildImportCsv({ siteCode, jobNo, day, orderNo }) {
  return [
    '站点编码,骑手工号,订单号,配送距离(公里),商品重量(斤),下单时间,送达时间,订单状态,订单金额,备注',
    `${siteCode},${jobNo},${orderNo},3.00,4.00,${day} 10:05:00,${day} 11:05:00,已完成,20.00,Cycle1 CDP 夹具`,
    '',
  ].join('\n');
}

export function uniqueOrderNo(prefix) {
  return `${prefix}${Date.now().toString(36).toUpperCase()}`;
}

export async function importCsv(apiUrl, token, { siteId, csv, filename = 'cycle1-import.csv', autoRecalc = true }) {
  const form = new FormData();
  form.append('file', new Blob([csv], { type: 'text/csv' }), filename);
  form.append('site_id', String(siteId));
  form.append('skip_errors', 'false');
  form.append('auto_recalc', autoRecalc ? 'true' : 'false');
  const { res, json } = await apiFetch(
    apiUrl,
    token,
    'POST',
    '/api/v1/rider-salary/orders/import',
    form,
  );
  if (!res.ok) {
    throw new Error(`导入失败 HTTP ${res.status}：${JSON.stringify(json).slice(0, 300)}`);
  }
  return json?.data;
}

export function failedPeriodIdsFromJob(job) {
  const payload = job?.payload || {};
  const ids = [
    ...(payload.failed_period_ids || []),
    ...(payload.period_ids || []),
    ...((payload.failed || []).map((row) => row.period_id)),
  ]
    .map(Number)
    .filter((n) => Number.isFinite(n) && n > 0);
  return [...new Set(ids)];
}

export async function pickAntOption(page, root, optionRe) {
  const select = root.locator('.ant-select').first();
  await select.click();
  const opt = page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: optionRe }).first();
  await opt.waitFor({ state: 'visible', timeout: 15000 });
  await opt.click();
}

export async function openImportWizard(page) {
  await page.getByRole('button', { name: /^导入$/ }).first().click();
  await page.getByText('导入后自动重算').waitFor({ state: 'visible', timeout: 20000 });
}

export async function wizardImport(page, { siteCode, csv, autoRecalc }) {
  await openImportWizard(page);
  const modal = page.getByRole('dialog').or(page.locator('[data-slot="dialog-content"]')).last();
  await pickAntOption(page, modal, new RegExp(siteCode));
  const auto = page.getByRole('checkbox', { name: /导入后自动重算/ });
  const checked = await auto.isChecked().catch(() => false);
  if (autoRecalc && !checked) await auto.check();
  if (!autoRecalc && checked) await auto.uncheck();
  await page.locator('input[type=file]').first().setInputFiles({
    name: 'cycle1-import.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(csv, 'utf8'),
  });
  await page.getByRole('button', { name: /开始导入/ }).click();
}

/**
 * GET /recalc-jobs/latest?site_id= （PR #16，#14 已接）
 * 成功：HTTP 200，data = { site_id, job }，job 可空。不 404。不得 skip。
 */
export async function findLatestRecalcJob({ apiUrl, token, siteId, knownId }) {
  if (knownId) {
    const known = await apiFetch(
      apiUrl,
      token,
      'GET',
      `/api/v1/rider-salary/recalc-jobs/${knownId}`,
    );
    if (known.res.ok && known.json?.data?.id) {
      return { job: known.json.data, via: 'id', http: known.res.status };
    }
  }
  const latest = await apiFetch(
    apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/recalc-jobs/latest?site_id=${siteId}`,
  );
  if (!latest.res.ok) {
    throw new Error(
      `GET /recalc-jobs/latest?site_id=${siteId} 须 HTTP 200（job 可空，不 404）。实际 ${latest.res.status}：${JSON.stringify(latest.json).slice(0, 200)}`,
    );
  }
  const payload = latest.json?.data;
  if (!payload || !Object.prototype.hasOwnProperty.call(payload, 'job')) {
    throw new Error(
      `GET /recalc-jobs/latest 须返回 { site_id, job }（job 可空），实际：${JSON.stringify(payload).slice(0, 300)}`,
    );
  }
  return {
    job: payload.job || null,
    via: 'latest',
    http: 200,
    siteId: payload.site_id,
  };
}

export function lockErrorLocator(page) {
  return page.locator('#period-lock-error, [data-testid="period-lock-error"]');
}

export async function clickPeriodLock(page, period) {
  await page.keyboard.press('Escape').catch(() => {});
  const drawerClose = page.locator('.ant-drawer-close, [data-slot="drawer"] button').first();
  if (await drawerClose.isVisible().catch(() => false)) {
    await drawerClose.click().catch(() => {});
  }
  const rows = page.locator('.vxe-body--row, .vxe-table--body tr');
  const start = period.start_date || '';
  let row = rows.filter({ hasText: start }).filter({ hasNotText: LOCK_JOB_NO });
  const siteLevel = row.filter({ hasText: '—' });
  if ((await siteLevel.count()) > 0) row = siteLevel;
  const target = row.first();
  await target.waitFor({ state: 'visible', timeout: 20000 }).catch(() => {});
  const lockInRow = target.getByText('锁账', { exact: true });
  if ((await lockInRow.count()) > 0) {
    await lockInRow.first().click();
    return;
  }
  const more = target.getByText(/更多|更多操作/);
  if ((await more.count()) > 0) {
    await more.first().click();
    await page.getByRole('menuitem', { name: /^锁账$/ }).click();
    return;
  }
  const anyLock = page.getByText('锁账', { exact: true }).first();
  await anyLock.waitFor({ state: 'visible', timeout: 15000 });
  await anyLock.click();
}

export async function submitLockReasonIfAsked(page) {
  const dialog = page.getByRole('dialog').or(page.locator('[data-slot="dialog-content"]'));
  const reasonDlg = dialog.filter({ hasText: /锁账原因|操作原因/ }).first();
  if (!(await reasonDlg.isVisible().catch(() => false))) return;
  const box = reasonDlg.locator('textarea, input').first();
  await box.fill('CDP 锁账同口径');
  await reasonDlg.getByRole('button', { name: /^确\s*定$/ }).click();
}

export async function siteLevelOpenPeriod({ apiUrl, token, siteId, month }) {
  const { res, json } = await apiFetch(
    apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/periods?site_id=${siteId}&month=${month}&page=1&size=50`,
  );
  if (!res.ok) throw new Error(`周期列表失败 ${res.status}`);
  const items = json?.data?.items || [];
  const open = items.filter((row) => row.status === 'open' || row.status === 'reopened');
  return (
    open.find((row) => Number(row.rider_id || 0) === 0) ||
    open.find((row) => !row.rider_job_no) ||
    open[0] ||
    null
  );
}

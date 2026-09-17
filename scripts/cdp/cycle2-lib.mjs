/**
 * Cycle 2 CDP 共用：金标 / 保底硬拦 / 导出需关注 / 分层勾稽 / 档案 / queued 替身。
 * 禁止截图即绿；trial 无数字 = FAIL（不得 WARN 过）。
 * 侧栏泄漏不改断言（已知红）。不写产品 UI。
 *
 * 钩子（#19）：period-export-confirm / period-export-attention-count /
 *   period-export-exclude-toggle / period-export-admit-attention /
 *   payroll-layers / payroll-reconciliation / payroll-deduction-remark /
 *   rider-goto-payroll / rider-binding-goto-calculate /
 *   period-calc-queued / period-calc-refresh
 * exclude_attention 须真正拿掉明细行（#20）；金标 C03/C04/C05A/C17 不得当缺失 skip。
 *
 * 叠 Cycle 1 CDP（#18）+ Cycle 2 前端（#19）+ Cycle 2 后端（#20）。
 * 具名：trial-case-gold / ops-plan-guarantee-last / ops-export-attention-parity /
 *   cdp-admin-payslip-layers / cdp-admin-deduction-remark /
 *   cdp-admin-calc-success-four-numbers / ops-rider-profile-to-payroll /
 *   ops-queued-calc-progress
 * trial-case-gold UI：点 FIX_C03 方案卡再点该表试算；禁止页面第一个试算（FIX_C05=3500）。
 * 日期须 2026-09-01～2026-09-30（面板默认上月）。
 */
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { apiFetch, authHeaders, siteMonth } from './cycle1-lib.mjs';

export const GOLD_C03_JOB = 'FIX_C03_R1';
export const GOLD_C05_JOB = 'FIX_C05_R1';
export const GOLD_C03_PLAN_CODE = 'FIX_C03';
export const GOLD_C03_PLAN_NAME = '金标C03全量落档';
/** 金标订单灌在 9 月；试算面板默认 lastNaturalMonth=上月，UI 必须显式改到这两天 */
export const GOLD_TRIAL_START = '2026-09-01';
export const GOLD_TRIAL_END = '2026-09-30';
export const GOLD_C03_GROSS = 8200;
export const GOLD_C04_GROSS = 7800;
export const GOLD_C05A_GROSS = 3500;
export const GOLD_C17_PERIOD_AMOUNT = 2310;
export const GOLD_C17_PLAN_AMOUNT = 100;

export const ATT_OVERTIME_NO = 'FIX_C2_ATT_OVERTIME';
export const ATT_REFUND_NO = 'FIX_C2_ATT_REFUND';
export const ATT_ABNORMAL_NO = 'FIX_C2_ATT_ABNORMAL';
export const ATTENTION_ORDER_NOS = [ATT_OVERTIME_NO, ATT_REFUND_NO, ATT_ABNORMAL_NO];

export const GUARANTEE_FAIL_COPY = /须放在周期阶段最后|须沉底/;
export const CONTAINS_ATTENTION_COPY = /本文件含需关注/;
export const RECON_COPY =
  /应发[\s\d.,]*[−\-–][\s\d.,]*代扣[\s\d.,]*[−\-–][\s\d.,]*预支抵扣[\s\d.,]*=[\s\d.,]*实发/;
export const LAYER_TITLES = ['应发', '代扣', '预支抵扣', '实发'];
export const EMPTY_REMARK_COPY = '无说明';
export const QUEUED_COPY = /排队中|计算中|已转入后台/;
export const REFRESH_COPY = /刷新预检|刷新结果|刷新预检\/结果/;
export const PROFILE_PAYROLL_CTA = /本骑手薪资结果/;
export const GOTO_CALC_COPY = /去周期算薪页|去算薪/;
export const TRIAL_AS_PAYROLL_COPY = /保存后需重新试算|保存后需\s*试算/;

export function parseMoney(text) {
  const raw = String(text || '').replace(/,/g, '').match(/-?\d+(?:\.\d+)?/);
  if (!raw) return NaN;
  return Number(raw[0]);
}

export function parseIntText(text) {
  // 优先取「订单 N 条」类中文数量，避免把「超时>60 分钟」里的 60 拼进去
  const labeled = String(text || '').match(/(?:订单|需关注|共|条数)\s*(\d+)/);
  if (labeled) return Number(labeled[1]);
  const first = String(text || '').match(/\d+/);
  return first ? Number(first[0]) : NaN;
}

export function moneyEquals(actual, expected, { eps = 0.009 } = {}) {
  return Number.isFinite(actual) && Math.abs(actual - Number(expected)) <= eps;
}

export function assertReconNumbers({ gross, deduction, advance, net }) {
  const g = Number(gross);
  const d = Number(deduction);
  const a = Number(advance);
  const n = Number(net);
  if (![g, d, a, n].every(Number.isFinite)) {
    throw new Error(`勾稽四数须为数字：应发=${gross} 代扣=${deduction} 预支=${advance} 实发=${net}`);
  }
  const left = Math.round((g - d - a) * 100) / 100;
  const right = Math.round(n * 100) / 100;
  if (left !== right) {
    throw new Error(`勾稽失败：应发(${g}) − 代扣(${d}) − 预支抵扣(${a}) = ${left}，实发=${right}`);
  }
}

export async function listSubjects(apiUrl, token) {
  const { res, json } = await apiFetch(apiUrl, token, 'GET', '/api/v1/rider-salary/subjects/all');
  if (!res.ok) throw new Error(`科目列表失败 HTTP ${res.status}`);
  return json?.data || [];
}

export function subjectByCode(subjects, code) {
  return (subjects || []).find((row) => row.code === code);
}

export async function findRiderByJobNo(apiUrl, token, siteId, jobNo) {
  const qs = new URLSearchParams({
    page: '1',
    size: '20',
    site_id: String(siteId),
    keyword: jobNo,
  });
  const { res, json } = await apiFetch(apiUrl, token, 'GET', `/api/v1/rider-salary/riders?${qs}`);
  if (!res.ok) throw new Error(`查找骑手 ${jobNo} 失败 HTTP ${res.status}`);
  return (json?.data?.items || []).find((r) => r.job_no === jobNo) || null;
}

export async function requireRiderByJobNo(apiUrl, token, siteId, jobNo) {
  const rider = await findRiderByJobNo(apiUrl, token, siteId, jobNo);
  if (!rider) {
    throw new Error(`未找到工号 ${jobNo}。请先运行 node scripts/cdp/seed-xiaoxiang-fixtures.mjs`);
  }
  return rider;
}

export async function findPlanByCode(apiUrl, token, code) {
  // name= 精确中文名；金标夹具用 code=FIX_C0x，改走 keyword 再按 code 精确匹配
  const qs = new URLSearchParams({ page: '1', size: '50', keyword: code });
  const { res, json } = await apiFetch(apiUrl, token, 'GET', `/api/v1/rider-salary/plans?${qs}`);
  if (!res.ok) throw new Error(`方案列表失败 HTTP ${res.status}`);
  return (json?.data?.items || []).find((p) => p.code === code) || null;
}

export async function listPlanVersions(apiUrl, token, planId) {
  const qs = new URLSearchParams({ page: '1', size: '50', plan_id: String(planId) });
  const { res, json } = await apiFetch(
    apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/plan-versions?${qs}`,
  );
  if (!res.ok) throw new Error(`方案版本列表失败 HTTP ${res.status}`);
  return json?.data?.items || [];
}

export async function getPlanVersion(apiUrl, token, versionId) {
  const { res, json } = await apiFetch(
    apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/plan-versions/${versionId}`,
  );
  if (!res.ok) throw new Error(`读取方案版本 ${versionId} 失败 HTTP ${res.status}`);
  return json?.data;
}

export async function putPlanItems(apiUrl, token, versionId, items) {
  return apiFetch(
    apiUrl,
    token,
    'PUT',
    `/api/v1/rider-salary/plan-versions/${versionId}/items`,
    items,
  );
}

export async function trialVersion(apiUrl, token, versionId, { riderId, start, end, mode }) {
  return apiFetch(apiUrl, token, 'POST', `/api/v1/rider-salary/plan-versions/${versionId}/trial`, {
    rider_id: Number(riderId),
    start_date: start,
    end_date: end,
    mode: mode || 'full_version',
  });
}

export async function activateVersion(apiUrl, token, versionId) {
  return apiFetch(apiUrl, token, 'POST', `/api/v1/rider-salary/plan-versions/${versionId}/activate`);
}

export async function copyPlanVersion(apiUrl, token, versionId) {
  const { res, json } = await apiFetch(
    apiUrl,
    token,
    'POST',
    `/api/v1/rider-salary/plan-versions/${versionId}/copy`,
  );
  if (!res.ok) {
    throw new Error(`复制方案版本失败 HTTP ${res.status}：${JSON.stringify(json).slice(0, 200)}`);
  }
  return json?.data;
}

export function c03Items(subjects) {
  const base = subjectByCode(subjects, 'BASE_UNIT_PRICE');
  const salary = subjectByCode(subjects, 'BASE_SALARY');
  const commission = subjectByCode(subjects, 'COMMISSION');
  if (!base || !salary || !commission) {
    throw new Error('金标科目缺失（BASE_UNIT_PRICE / BASE_SALARY / COMMISSION）');
  }
  return [
    {
      subject_id: base.id,
      name: '基础单价',
      stage: 'per_order',
      sort_order: 10,
      formula_json: { 类型: '固定金额', 金额: 3 },
      enabled: true,
    },
    {
      subject_id: salary.id,
      name: '底薪',
      stage: 'period',
      sort_order: 20,
      formula_json: { 类型: '表达式', 表达式: '3000 * 方案生效天数 / 周期天数' },
      enabled: true,
    },
    {
      subject_id: commission.id,
      name: '提成',
      stage: 'period',
      sort_order: 30,
      formula_json: {
        类型: '阶梯',
        字段: '周期有效单量',
        模式: '全量落档',
        计价: '按单价',
        档位: [
          { 下限: 0, 上限: 400, 值: 4 },
          { 下限: 400, 上限: 700, 值: 5 },
          { 下限: 700, 上限: null, 值: 6 },
        ],
      },
      enabled: true,
    },
  ];
}

export function c04Items(subjects) {
  const items = c03Items(subjects);
  const commission = items.find((row) => row.name === '提成');
  commission.formula_json = { ...commission.formula_json, 模式: '分段累进' };
  return items;
}

export function c05Items(subjects, { guaranteeLast = true } = {}) {
  const unit = subjectByCode(subjects, 'BASE_UNIT_PRICE');
  const guarantee = subjectByCode(subjects, 'GUARANTEE_TOPUP');
  const commission = subjectByCode(subjects, 'COMMISSION');
  if (!unit || !guarantee) {
    throw new Error('保底金标科目缺失（BASE_UNIT_PRICE / GUARANTEE_TOPUP）');
  }
  const perOrder = {
    subject_id: unit.id,
    name: '提成',
    stage: 'per_order',
    sort_order: 10,
    formula_json: { 类型: '固定金额', 金额: 3.5 },
    enabled: true,
  };
  const topup = {
    subject_id: guarantee.id,
    name: '保底补足',
    stage: 'period',
    sort_order: guaranteeLast ? 90 : 10,
    formula_json: { 类型: '表达式', 表达式: '最大值(0, 3500 - 本期已计金额)' },
    enabled: true,
  };
  const extra = {
    subject_id: (commission || unit).id,
    name: '周期加价',
    stage: 'period',
    sort_order: guaranteeLast ? 20 : 90,
    formula_json: { 类型: '固定金额', 金额: 0 },
    enabled: true,
  };
  return guaranteeLast ? [perOrder, extra, topup] : [perOrder, topup, extra];
}

export async function requireGoldVersion(apiUrl, token, code) {
  const plan = await findPlanByCode(apiUrl, token, code);
  if (!plan?.id) {
    throw new Error(`未找到金标方案 ${code}。请先运行 node scripts/cdp/seed-xiaoxiang-fixtures.mjs`);
  }
  const versions = await listPlanVersions(apiUrl, token, plan.id);
  const hit = versions[0];
  if (!hit?.id) {
    throw new Error(`方案 ${code} 无版本。请先灌种`);
  }
  return { plan, version: hit };
}

export async function attentionOrders({ apiUrl, token, siteId, month }) {
  const qs = new URLSearchParams({
    page: '1',
    size: '100',
    site_id: String(siteId),
    attention: 'true',
    date_from: `${month}-01`,
    date_to: `${month}-28`,
  });
  const { res, json } = await apiFetch(apiUrl, token, 'GET', `/api/v1/rider-salary/orders?${qs}`);
  if (!res.ok) {
    throw new Error(`GET /orders?attention=1 失败 HTTP ${res.status}：${JSON.stringify(json).slice(0, 200)}`);
  }
  return json?.data?.items || [];
}

export async function dashboardAttentionCount({ apiUrl, token, siteId, month }) {
  const qs = new URLSearchParams({ site_id: String(siteId), month });
  const { res, json } = await apiFetch(
    apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/dashboard/summary?${qs}`,
  );
  if (!res.ok) {
    throw new Error(`工作台 summary 失败 HTTP ${res.status}`);
  }
  const blocks = json?.data?.attention || [];
  const hit = blocks.find((b) => /异常|需关注/.test(`${b.title || ''}${b.key || ''}${b.code || ''}`));
  const count = Number(hit?.count ?? hit?.total ?? json?.data?.abnormal_order_count ?? NaN);
  return { blocks, count, raw: json?.data };
}

export async function pickPayrollWithMoney({ apiUrl, token, siteId, riderId }) {
  const qs = new URLSearchParams({
    page: '1',
    size: '50',
    site_id: String(siteId),
  });
  if (riderId) qs.set('rider_id', String(riderId));
  const { res, json } = await apiFetch(apiUrl, token, 'GET', `/api/v1/rider-salary/payrolls?${qs}`);
  if (!res.ok) throw new Error(`薪资结果列表失败 HTTP ${res.status}`);
  const items = json?.data?.items || [];
  if (!items.length) {
    throw new Error('本站无薪资结果，无法测勾稽分层 / 档案接薪资');
  }
  return items.find((row) => Number(row.gross) > 0) || items[0];
}

export async function getPayrollDetail(apiUrl, token, payrollId) {
  const { res, json } = await apiFetch(
    apiUrl,
    token,
    'GET',
    `/api/v1/rider-salary/payrolls/${payrollId}`,
  );
  if (!res.ok) throw new Error(`薪资明细 ${payrollId} 失败 HTTP ${res.status}`);
  return json?.data;
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

export async function exportPeriodBlob({ apiUrl, token, periodId, excludeAttention }) {
  const qs = new URLSearchParams();
  if (excludeAttention === true) qs.set('exclude_attention', 'true');
  if (excludeAttention === false) qs.set('exclude_attention', 'false');
  const suffix = qs.toString() ? `?${qs}` : '';
  const res = await fetch(`${apiUrl}/api/v1/rider-salary/periods/${periodId}/export${suffix}`, {
    headers: authHeaders(token),
  });
  const buf = Buffer.from(await res.arrayBuffer());
  return {
    res,
    buf,
    text: buf.toString('utf8'),
    attentionCount: res.headers.get('x-qipay-attention-count'),
    attentionExcluded: res.headers.get('x-qipay-attention-excluded'),
  };
}

export function xlsxText(buf) {
  const raw = Buffer.isBuffer(buf) ? buf : Buffer.from(buf);
  const latin1 = raw.toString('latin1');
  const tmp = path.join(os.tmpdir(), `cdp-export-${process.pid}-${Date.now()}.xlsx`);
  try {
    fs.writeFileSync(tmp, raw);
    const out = execFileSync(
      'python3',
      [
        '-c',
        'import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); print("".join(z.read(n).decode("utf-8","ignore") for n in z.namelist()))',
        tmp,
      ],
      { encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 },
    );
    return `${latin1}\n${out}`;
  } catch {
    return latin1;
  } finally {
    try {
      fs.unlinkSync(tmp);
    } catch {
      /* ignore */
    }
  }
}

export async function clickPeriodExport(page, period) {
  for (let i = 0; i < 3; i += 1) {
    await page.keyboard.press('Escape').catch(() => {});
    await page.waitForTimeout(150);
  }
  const openLayer = page.locator(
    '[data-state="open"][role="dialog"], .ant-drawer-open, [data-slot="drawer"][data-state="open"]',
  );
  if ((await openLayer.count()) > 0) {
    await page.locator('.ant-drawer-close, [data-slot="drawer"] button').first().click({ force: true }).catch(() => {});
    await page.keyboard.press('Escape').catch(() => {});
    await openLayer.first().waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {});
  }
  const rows = page.locator('.vxe-body--row, .vxe-table--body tr');
  const start = period?.start_date || '';
  const siteHint = period?.site_name || period?.site_code || '福民|SZ0050';
  let row = start ? rows.filter({ hasText: start }) : rows;
  row = row.filter({ hasText: new RegExp(siteHint) });
  const siteLevel = row.filter({ hasText: '—' });
  if ((await siteLevel.count()) > 0) row = siteLevel;
  if ((await row.count()) === 0) {
    row = start ? rows.filter({ hasText: start }).filter({ hasText: '—' }) : rows;
  }
  const target = row.first();
  await target.waitFor({ state: 'visible', timeout: 20000 }).catch(() => {});
  const exportInRow = target.getByText('导出', { exact: true });
  if ((await exportInRow.count()) > 0) {
    await exportInRow.first().click({ force: true });
    return;
  }
  const more = target.getByText(/更多|更多操作/);
  if ((await more.count()) > 0) {
    await more.first().click({ force: true });
    await page.getByRole('menuitem', { name: /^导出$/ }).click();
    return;
  }
  const anyExport = page.getByRole('button', { name: /导出/ }).first();
  await anyExport.waitFor({ state: 'visible', timeout: 15000 });
  await anyExport.click({ force: true });
}

export function xlsxContainsOrderNo(buf, orderNo) {
  return xlsxText(buf).includes(orderNo);
}

function escapeRe(value) {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function trialDrawer(page) {
  const byMode = page.getByTestId('trial-mode');
  return page
    .locator('[data-state="open"], .ant-drawer-open, [role="dialog"]')
    .filter({ has: byMode })
    .first();
}

/**
 * 点左侧方案卡（code 精确匹配，避免 FIX_C03 命中 FIX_C03_R1）。
 * 找不到 → FAIL，禁止回落页面第一个「试算」（id desc 默认 FIX_C05=3500）。
 */
export async function selectPlanCard(page, { code, name } = {}) {
  if (!code && !name) {
    throw new Error('selectPlanCard 须给 code 或名称，禁止点第一个方案/试算');
  }
  let card = page.locator('button[type="button"]');
  if (code) {
    const codeRe = new RegExp(`^${escapeRe(code)}$`);
    card = card.filter({ has: page.locator('span').filter({ hasText: codeRe }) });
  }
  if (name) {
    card = card.filter({ hasText: name });
  }
  const count = await card.count();
  if (count === 0) {
    throw new Error(
      `未找到方案卡 ${name || ''} ${code || ''}。禁止回落页面第一个「试算」（id desc 默认 FIX_C05=3500）。请先灌种。`,
    );
  }
  await card.first().click();
  if (name) {
    await page
      .getByText(new RegExp(`${escapeRe(name)}\\s*的版本`))
      .first()
      .waitFor({ state: 'visible', timeout: 20000 });
  }
}

/**
 * 先选方案卡，再点该方案版本表里的「试算」。不得用页面第一个试算。
 */
export async function openSelectedPlanTrial(page, { code, name } = {}) {
  await selectPlanCard(page, { code, name });
  const heading = page.locator('.font-medium').filter({ hasText: /的版本/ }).first();
  await heading.waitFor({ state: 'visible', timeout: 20000 });
  const headingText = (await heading.innerText()) || '';
  if (name && !headingText.includes(name)) {
    throw new Error(
      `右侧版本表标题须含「${name}」，实际=${headingText}。禁止试算未选中方案。`,
    );
  }
  const table = page.locator('.ant-table').filter({ has: page.getByRole('button', { name: /^试算$/ }) }).first();
  const trialBtn = table.getByRole('button', { name: /^试算$/ }).first();
  if ((await trialBtn.count()) === 0) {
    throw new Error(
      `${code || name} 版本表无「试算」。禁止回落页面第一个试算（那是 FIX_C05=3500）。`,
    );
  }
  await trialBtn.click();
  const mode = page.getByTestId('trial-mode');
  await mode.waitFor({ state: 'visible', timeout: 30000 });
  return mode;
}

export async function openTrialDrawer(page, opts = {}) {
  const code = opts.planCode || opts.code;
  const name = opts.planName || opts.name;
  if (!code && !name) {
    throw new Error(
      'openTrialDrawer 须指定 planCode/planName。页面第一个试算是 id desc 最新方案（种子后 FIX_C05，应发 3500），禁止回落。',
    );
  }
  return openSelectedPlanTrial(page, { code, name });
}

async function fillTrialRange(page, start, end) {
  const root = (await trialDrawer(page).count()) ? trialDrawer(page) : page;
  const inputs = root.locator('.ant-picker-input input, .ant-picker input');
  if ((await inputs.count()) < 2) {
    throw new Error('试算日期选择器缺失');
  }
  async function setInput(idx, value) {
    const input = inputs.nth(idx);
    await input.click({ force: true });
    await input.fill('');
    await page.keyboard.press('Control+A').catch(() => {});
    await page.keyboard.type(String(value), { delay: 15 });
    await page.keyboard.press('Enter');
    const got = await input.inputValue();
    if (!String(got).includes(value)) {
      await input.fill(value);
      await input.blur().catch(() => {});
    }
  }
  await setInput(0, start);
  await setInput(1, end);
  await page.keyboard.press('Escape').catch(() => {});
  const startVal = await inputs.nth(0).inputValue();
  const endVal = await inputs.nth(1).inputValue();
  if (!String(startVal).includes(start) || !String(endVal).includes(end)) {
    throw new Error(
      `试算日期须为 ${start}～${end}，实际=${startVal}～${endVal}（默认上月会落到空月，C03 不是 8200）`,
    );
  }
}

export async function fillTrialTargets(page, { siteCode, jobNo, start, end }) {
  const root = (await trialDrawer(page).count()) ? trialDrawer(page) : page;
  const selects = root.locator('.ant-select');
  if ((await selects.count()) > 0) {
    await selects.nth(0).click();
    await page.waitForTimeout(200);
    await page.keyboard.type(String(siteCode), { delay: 20 });
    await page.waitForTimeout(400);
    const siteOpt = page
      .locator('.ant-select-dropdown:visible .ant-select-item-option')
      .filter({ hasText: new RegExp(escapeRe(siteCode)) })
      .first();
    await siteOpt.waitFor({ state: 'visible', timeout: 15000 });
    await siteOpt.click({ force: true });
  }
  if ((await selects.count()) > 1) {
    await selects.nth(1).click();
    await page.waitForTimeout(200);
    await page.keyboard.type(String(jobNo), { delay: 20 });
    await page.waitForTimeout(400);
    const riderOpt = page
      .locator('.ant-select-dropdown:visible .ant-select-item-option')
      .filter({ hasText: new RegExp(escapeRe(jobNo)) })
      .first();
    await riderOpt.waitFor({ state: 'visible', timeout: 15000 });
    await riderOpt.click({ force: true });
  }
  if (start && end) {
    await fillTrialRange(page, start, end);
  }
}

export async function clickStartTrial(page) {
  const confirm = page.getByRole('button', { name: /开始试算/ }).first();
  await confirm.waitFor({ state: 'visible', timeout: 15000 });
  await confirm.click();
}

export async function waitTrialNumbers(page) {
  const validEl = page.getByTestId('trial-valid-order-count');
  const planEl = page.getByTestId('trial-plan-order-count');
  try {
    await validEl.waitFor({ state: 'visible', timeout: 60000 });
    await planEl.waitFor({ state: 'visible', timeout: 15000 });
  } catch {
    throw new Error(
      'trial-binding-segments 无试算结果数字 = FAIL（禁止 WARN 过）。请点「开始试算」并灌 FIX_C17_R1 换绑夹具。',
    );
  }
  const valid = parseIntText(await validEl.innerText());
  const plan = parseIntText(await planEl.innerText());
  if (!(Number.isFinite(valid) && Number.isFinite(plan))) {
    throw new Error(`单量口径非数字：valid=${await validEl.innerText()} plan=${await planEl.innerText()}`);
  }
  return { valid, plan };
}

export async function readTrialGross(page) {
  const result = page.getByTestId('trial-result');
  await result.waitFor({ state: 'visible', timeout: 60000 });
  const grossCard = result
    .locator('.ant-card')
    .filter({ has: page.locator('.text-xs, .text-muted-foreground').filter({ hasText: /^应发$/ }) })
    .first();
  await grossCard.waitFor({ state: 'visible', timeout: 60000 }).catch(() => {});
  const scoped = (await grossCard.count()) > 0 ? grossCard : result;
  await page
    .waitForFunction(
      () => {
        const el = document.querySelector('[data-testid="trial-result"]');
        return el && /应发[\s\S]{0,40}\d/.test(el.innerText || '');
      },
      null,
      { timeout: 60000 },
    )
    .catch(() => {});
  const text = await scoped.innerText();
  const m = String(text).match(/应发[^\d\-]*(-?\d[\d,]*(?:\.\d+)?)/);
  const amount = m ? parseMoney(m[1]) : parseMoney(text);
  if (!Number.isFinite(amount)) {
    throw new Error(`试算结果未见应发数字：${text.slice(0, 200)}`);
  }
  return amount;
}

export { apiFetch, authHeaders, siteMonth };

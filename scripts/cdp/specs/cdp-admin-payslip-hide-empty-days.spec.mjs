/** CDP: cdp-admin-payslip-hide-empty-days — /payroll/:id 按日空行默认折叠（#30 钩子） */
import { apiFetch } from '../cycle1-lib.mjs';
import {
  LAYER_TITLES,
  RECON_COPY,
  assertReconNumbers,
  getPayrollDetail,
  parseMoney,
  siteMonth,
} from '../cycle2-lib.mjs';
import {
  DAILY_NET_COPY,
  DAILY_NET_HINT,
  DAILY_NET_NOT_PERIOD_COPY,
  PR30_PAYSLIP_HOOKS,
  PR30_PAYSLIP_LAYER_HOOKS,
  SHOW_EMPTY_DAYS_COPY,
  assertLockedGoldUnchanged,
  bizDateOf,
  classifyDailies,
  requireHooks,
  requireTestId,
  visibleDailyDates,
} from '../cycle5-lib.mjs';

export const name = 'cdp-admin-payslip-hide-empty-days';

async function pickPayrollWithEmptyDays({ apiUrl, token, siteId }) {
  const qs = new URLSearchParams({ page: '1', size: '50', site_id: String(siteId) });
  const { res, json } = await apiFetch(apiUrl, token, 'GET', `/api/v1/rider-salary/payrolls?${qs}`);
  if (!res.ok) throw new Error(`薪资结果列表失败 HTTP ${res.status}，不得 skip`);
  const items = json?.data?.items || [];
  if (!items.length) throw new Error('本站无薪资结果，无法测按日空行，不得 skip');
  for (const row of items) {
    const detail = await getPayrollDetail(apiUrl, token, row.id);
    const classified = classifyDailies(detail);
    if (classified.hidden.length) return { row, detail, classified };
  }
  throw new Error(
    '本站薪资结果无默认应藏空日（not_imported / 零单且无金额/奖惩/预支）。夹具须含未导入或空日，不得 skip',
  );
}

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId } = siteMonth();
  const { row, detail, classified } = await pickPayrollWithEmptyDays({
    apiUrl: config.apiUrl,
    token,
    siteId,
  });

  assertReconNumbers({
    gross: detail.gross,
    deduction: detail.deduction_total,
    advance: detail.advance_deduction,
    net: detail.net,
  });
  if (!Array.isArray(detail.dailies) || !detail.dailies.length) {
    throw new Error('不得删 dailies。明细 API 须仍返回按日行');
  }

  await page.goto(`${config.adminUrl}/rider-salary/payroll/${row.id}`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());

  await requireHooks(page, PR30_PAYSLIP_LAYER_HOOKS, 'Cycle 2 分层钩子缺失，不得 skip');
  const layers = page.getByTestId('payroll-layers');
  const layersText = await layers.innerText();
  const missingTitles = LAYER_TITLES.filter((title) => !layersText.includes(title));
  if (missingTitles.length) {
    throw new Error(`payroll-layers 缺分区标题：${missingTitles.join('、')}`);
  }
  const recon = page.getByTestId('payroll-reconciliation');
  const reconBefore = await recon.innerText();
  if (!RECON_COPY.test(reconBefore)) {
    throw new Error(`勾稽句须仍是 应发 − 代扣 − 预支抵扣 = 实发：${reconBefore}`);
  }
  if (detail.stale) {
    await requireTestId(page, 'payroll-stale-banner', '禁止用折叠掩饰 stale：须仍见 payroll-stale-banner');
  }

  await page.getByRole('tab', { name: '按日' }).click();
  await requireTestId(page, 'payroll-detail-tabs', '未见 payroll-detail-tabs，不得 skip');
  await requireHooks(page, PR30_PAYSLIP_HOOKS, '#30 按日空日钩子缺失，不得 skip');

  const toggle = page.getByTestId('payroll-show-empty-days');
  if (await toggle.isChecked()) {
    throw new Error('payroll-show-empty-days 须默认未勾。列表忽略开关仍铺满空行 = FAIL');
  }
  const countText = (await page.getByTestId('payroll-empty-day-count').innerText()).trim();
  if (String(classified.hidden.length) !== countText) {
    throw new Error(
      `「显示空日（N）」N 须=${classified.hidden.length}，实际=${countText}，不得 skip`,
    );
  }
  const toolbar = await page.getByTestId('cdp-admin-payslip-hide-empty-days').innerText();
  if (!SHOW_EMPTY_DAYS_COPY.test(toolbar)) {
    throw new Error('按日 Tab 须有入口「显示空日（N）」。列表忽略该开关仍铺满空行 = FAIL，不得 skip');
  }
  const hint = await page.getByTestId('payroll-daily-net-hint').innerText();
  if (!hint.includes(DAILY_NET_HINT) && (!DAILY_NET_COPY.test(hint) || !DAILY_NET_NOT_PERIOD_COPY.test(hint))) {
    throw new Error('payroll-daily-net-hint 须能读出：按日「净」= 当日公式+奖−惩，不是周期实发');
  }
  if (await page.getByTestId('payroll-empty-day-row').count()) {
    throw new Error('默认不见 payroll-empty-day-row。列表忽略「显示空日」仍铺满空行 = FAIL');
  }

  const hiddenDates = classified.hidden.map((item) => bizDateOf(item.biz_date));
  const visibleDates = classified.visible.map((item) => bizDateOf(item.biz_date));
  const shown = await visibleDailyDates(page);
  const leaked = hiddenDates.filter((date) => shown.includes(date));
  if (leaked.length) {
    throw new Error(
      `默认须藏空日，实际仍见：${leaked.join('、')}。列表忽略「显示空日」仍铺满空行 = FAIL`,
    );
  }
  const missingVisible = visibleDates.filter((date) => !shown.includes(date));
  if (missingVisible.length) {
    throw new Error(
      `有奖 / 有惩 / 预支 / no_plan 有完成单的日须默认可见。缺：${missingVisible.join('、')}`,
    );
  }

  await toggle.click();
  await page.waitForTimeout(400);
  if (!(await toggle.isChecked())) {
    throw new Error('勾选「显示空日」后开关须为勾选');
  }
  await requireTestId(page, 'payroll-empty-day-row', '打开「显示空日」后须出现 payroll-empty-day-row，不得 skip');
  const expanded = await visibleDailyDates(page);
  const stillHidden = hiddenDates.filter((date) => !expanded.includes(date));
  if (stillHidden.length) {
    throw new Error(`打开「显示空日」后仍不见空日：${stillHidden.join('、')}`);
  }
  const expandedBody = await page.locator('body').innerText();
  if (!/未导入|无单|零单/.test(expandedBody)) {
    throw new Error('展开后仍须见未导入 / 无单 Tag');
  }
  const reconAfter = await recon.innerText();
  if (reconAfter !== reconBefore) {
    throw new Error(`摘要勾稽不得因折叠改变。折叠前 ${reconBefore} 折叠后 ${reconAfter}`);
  }
  assertReconNumbers({
    gross: parseMoney(detail.gross),
    deduction: parseMoney(detail.deduction_total),
    advance: parseMoney(detail.advance_deduction),
    net: parseMoney(detail.net),
  });

  const dateLink = page.getByTestId('payroll-dailies').locator('a').filter({ hasText: /^\d{4}-\d{2}-\d{2}$/ }).first();
  if (await dateLink.count()) {
    await dateLink.click();
    await page.waitForTimeout(500);
    if (!/\/rider-salary\/order/.test(page.url())) {
      throw new Error(`点日期深链不得回退。实际 ${page.url()}`);
    }
    await page.goBack({ waitUntil: 'networkidle' }).catch(() => {});
  }
  await page.goto(`${config.adminUrl}/rider-salary/payroll/${row.id}`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  const countLink = page.getByTestId('payroll-order-count-link');
  if (await countLink.count()) {
    await countLink.click();
    await page.waitForTimeout(500);
    if (!/\/rider-salary\/order/.test(page.url())) {
      throw new Error(`点单量深链不得回退。实际 ${page.url()}`);
    }
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-admin-payslip-hide-empty-days');
}

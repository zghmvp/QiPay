/** CDP: ops-export-adjustment-sheet — 已入账/未入账可分；排除订单默认仍导出奖惩并标注 */
import { siteLevelOpenPeriod, siteMonth } from '../cycle1-lib.mjs';
import { ATTENTION_ORDER_NOS, clickPeriodExport, xlsxContainsOrderNo } from '../cycle2-lib.mjs';
import {
  ADJ_ADMIT_COPY,
  ADJ_ATT_REMARK,
  ADJ_DROP_COPY,
  ADJ_OPEN_REMARK,
  ADJ_POSTED_REMARK,
  ATT_ADJ_MARK,
  OPEN_ADJ_COPY,
  POSTED_ADJ_COPY,
  assertNoSkipHttp,
  excludeFlagFromUrl,
  exportPeriodBlobCycle3,
  xlsxSheetCells,
} from '../cycle3-lib.mjs';

export const name = 'ops-export-adjustment-sheet';

function requireAdjSheet(buf, label) {
  const text = xlsxSheetCells(buf, '奖惩记录');
  if (text.startsWith('SHEETS:')) {
    throw new Error(`${label}：导出无「奖惩记录」sheet。实际 ${text}`);
  }
  return text;
}

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();
  const period = await siteLevelOpenPeriod({ apiUrl: config.apiUrl, token, siteId, month });
  if (!period?.id) throw new Error('本站无开放周期，无法测奖惩 sheet');

  const included = await exportPeriodBlobCycle3({
    apiUrl: config.apiUrl,
    token,
    periodId: period.id,
    excludeAttention: false,
    excludeAttentionAdjustments: false,
  });
  assertNoSkipHttp(included.res, '导出（默认不排除）');
  if (!included.res.ok) {
    throw new Error(`导出失败 HTTP ${included.res.status}`);
  }
  const adjSheet = requireAdjSheet(included.buf, '默认导出');
  if (!POSTED_ADJ_COPY.test(adjSheet) || !OPEN_ADJ_COPY.test(adjSheet)) {
    throw new Error(`奖惩 sheet 须能分开已入账 vs 未入账。实际：${adjSheet.slice(0, 400)}`);
  }
  if (!adjSheet.includes(ADJ_POSTED_REMARK) && !adjSheet.includes('已入账')) {
    throw new Error(`已入账奖惩夹具 ${ADJ_POSTED_REMARK} 须出现在已入账分区`);
  }
  if (!adjSheet.includes(ADJ_OPEN_REMARK) && !OPEN_ADJ_COPY.test(adjSheet)) {
    throw new Error(`未入账奖惩夹具 ${ADJ_OPEN_REMARK} 须标注未入账，不得冒充已出账`);
  }

  const excludedOrders = await exportPeriodBlobCycle3({
    apiUrl: config.apiUrl,
    token,
    periodId: period.id,
    excludeAttention: true,
    excludeAttentionAdjustments: false,
  });
  assertNoSkipHttp(excludedOrders.res, '导出 exclude_attention=true');
  if (!excludedOrders.res.ok) {
    throw new Error(`排除订单导出失败 HTTP ${excludedOrders.res.status}`);
  }
  const leaked = ATTENTION_ORDER_NOS.filter((no) => xlsxContainsOrderNo(excludedOrders.buf, no));
  if (leaked.length === ATTENTION_ORDER_NOS.length) {
    throw new Error('排除订单后明细仍应拿掉需关注单（Cycle 2 合同）');
  }
  const adjAfter = requireAdjSheet(excludedOrders.buf, '排除订单、奖惩不同步');
  if (!adjAfter.includes(ADJ_ATT_REMARK) && !ATT_ADJ_MARK.test(adjAfter)) {
    throw new Error(
      `排除需关注默认仍导出全部奖惩，且须标注「该骑手该日存在需关注订单」。实际：${adjAfter.slice(0, 400)}`,
    );
  }
  if (!ATT_ADJ_MARK.test(adjAfter)) {
    throw new Error(`与超时单同日同骑手的奖惩须带需关注标注：${adjAfter.slice(0, 300)}`);
  }

  const syncOn = await exportPeriodBlobCycle3({
    apiUrl: config.apiUrl,
    token,
    periodId: period.id,
    excludeAttention: true,
    excludeAttentionAdjustments: true,
  });
  if ([404, 405, 422, 501].includes(syncOn.res.status)) {
    throw new Error(
      `exclude_attention_adjustments=true HTTP ${syncOn.res.status}。可选同步排除须落地，不得 skip`,
    );
  }
  if (syncOn.res.ok) {
    const adjSync = requireAdjSheet(syncOn.buf, '奖惩同步排除');
    if (adjSync.includes(ADJ_ATT_REMARK) && ATT_ADJ_MARK.test(adjSync)) {
      throw new Error('奖惩同步排除打开后，与需关注同日同骑手的奖惩行须消失');
    }
  }

  const exportUrls = [];
  page.on('request', (req) => {
    if (/\/rider-salary\/periods\/\d+\/export/.test(req.url())) {
      exportUrls.push(req.url());
    }
  });
  await page.route('**/api/v1/rider-salary/periods/*/export**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      body: Buffer.from('PK'),
      headers: { 'content-disposition': 'attachment; filename="cycle3-export.xlsx"' },
    });
  });

  await page.goto(
    `${config.adminUrl}/rider-salary/period?site_id=${siteId}&month=${month}&id=${period.id}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await clickPeriodExport(page, period);
  const box = page.getByTestId('period-export-confirm');
  await box.waitFor({ state: 'visible', timeout: 20000 });

  const posted = page.getByTestId('period-export-adj-booked');
  try {
    await posted.waitFor({ state: 'visible', timeout: 15000 });
  } catch {
    throw new Error('确认框须见 period-export-adj-booked（本周期已入账奖惩条数），不得 skip');
  }
  const postedText = await posted.innerText();
  if (!/已入账/.test(postedText) || !/\d+/.test(postedText)) {
    throw new Error(`已入账奖惩条数须中文可见：${postedText}`);
  }
  const unbooked = page.getByTestId('period-export-adj-unbooked');
  try {
    await unbooked.waitFor({ state: 'visible', timeout: 10000 });
  } catch {
    throw new Error('确认框须见 period-export-adj-unbooked（窗口内未入账）');
  }
  const unbookedText = await unbooked.innerText();
  if (!/未入账/.test(unbookedText)) {
    throw new Error(`未入账奖惩须中文可见：${unbookedText}`);
  }

  const annotation = page.getByTestId('period-export-adj-annotation');
  await annotation.waitFor({ state: 'visible', timeout: 10000 });
  const annText = await annotation.innerText();
  if (!ATT_ADJ_MARK.test(annText)) {
    throw new Error(`period-export-adj-annotation 须含「该骑手该日存在需关注订单」：${annText}`);
  }

  const adjToggle = page.getByTestId('period-export-adj-sync-toggle');
  await adjToggle.waitFor({ state: 'visible', timeout: 10000 });
  const adjOn =
    (await adjToggle.getAttribute('aria-checked')) === 'true' ||
    (await adjToggle.isChecked().catch(() => false));
  if (adjOn) {
    throw new Error('奖惩同步排除开关 period-export-adj-sync-toggle 默认必须关闭');
  }
  const admitAdj = page.getByTestId('period-export-adj-admit');
  if (await admitAdj.isVisible().catch(() => false)) {
    const admitText = await admitAdj.innerText();
    if (!ADJ_ADMIT_COPY.test(admitText) && !/含与需关注同日同骑手/.test(admitText)) {
      throw new Error(`关同步排除时须承认奖惩含需关注同日同骑手：${admitText}`);
    }
  }

  await adjToggle.click();
  const drop = page.getByTestId('period-export-adj-sync-drop-count');
  try {
    await drop.waitFor({ state: 'visible', timeout: 10000 });
  } catch {
    throw new Error('打开奖惩同步排除后须写清将少 N 条（period-export-adj-sync-drop-count）');
  }
  const dropText = await drop.innerText();
  if (!ADJ_DROP_COPY.test(dropText) && !/少\s*\d+/.test(dropText)) {
    throw new Error(`打开同步排除须写清奖惩将少 N 条：${dropText}`);
  }

  const copy = await box.innerText();
  helpers.assertNoPaymentTaxCopy(copy);
  if (/银行代发|打款文件/.test(copy)) {
    throw new Error('应发导出不得冒充打款文件');
  }

  await page.getByRole('button', { name: /确认导出/ }).first().click();
  await page.waitForTimeout(400);
  const syncUrl = exportUrls.find(
    (url) => excludeFlagFromUrl(url, 'exclude_attention_adjustments') === true,
  );
  if (!syncUrl) {
    throw new Error(
      `同步排除打开后请求须带 exclude_attention_adjustments=true。实际：${exportUrls.join(' | ') || '(无)'}`,
    );
  }

  await helpers.shot(page, 'cdp-ops-export-adjustment-sheet');
}

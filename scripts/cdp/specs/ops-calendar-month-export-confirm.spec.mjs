/** CDP: ops-calendar-month-export-confirm — #27 日历导出先确认；多周期 period-export-period-row */
import { resolveFixRiderId, siteMonth } from '../cycle1-lib.mjs';
import { CONTAINS_ATTENTION_COPY } from '../cycle2-lib.mjs';
import { assertNoExportBeforeConfirm, queryOf, requireTestId } from '../cycle4-lib.mjs';

export const name = 'ops-calendar-month-export-confirm';

const PERIOD_A = 91001;
const PERIOD_B = 91002;

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const { siteId, month } = siteMonth();
  const riderId = await resolveFixRiderId(config.apiUrl, admin.access_token, siteId);
  const dateFrom = `${month}-01`;
  const dateTo = `${month}-30`;

  const exportUrls = [];
  page.on('request', (req) => {
    if (/\/api\/v1\/rider-salary\/periods\/\d+\/export/.test(req.url())) {
      exportUrls.push(req.url());
    }
  });
  await page.route('**/api/v1/rider-salary/periods/*/export**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      body: Buffer.from('PK'),
      headers: { 'content-disposition': 'attachment; filename="cycle4-month.xlsx"' },
    });
  });

  await page.route('**/api/v1/rider-salary/calendar/**', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    const res = await route.fetch();
    const json = await res.json();
    const data = json?.data || {};
    const summary = { ...(data.summary || {}) };
    summary.periods = [
      { id: PERIOD_A, start_date: dateFrom, end_date: `${month}-15`, status: 'open' },
      { id: PERIOD_B, start_date: `${month}-16`, end_date: dateTo, status: 'open' },
    ];
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: json?.code ?? 200, msg: json?.msg ?? '成功', data: { ...data, summary } }),
    });
  });

  const periodPayload = (id, attention, booked, unbooked) => ({
    code: 200,
    msg: '成功',
    data: {
      id,
      attention_order_count: attention,
      booked_adjustment_count: booked,
      unbooked_adjustment_count: unbooked,
      attention_adjustment_count: 1,
    },
  });
  await page.route(`**/api/v1/rider-salary/periods/${PERIOD_A}`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(periodPayload(PERIOD_A, 3, 2, 1)),
    });
  });
  await page.route(`**/api/v1/rider-salary/periods/${PERIOD_B}`, async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(periodPayload(PERIOD_B, 4, 5, 2)),
    });
  });

  await page.goto(
    `${config.adminUrl}/rider-salary/calendar?site_id=${siteId}&rider_id=${riderId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );

  await requireTestId(page, 'calendar-export-month', '未见 #27 按钮 calendar-export-month');
  await page.getByTestId('calendar-export-month').first().click();
  await page.waitForTimeout(400);
  assertNoExportBeforeConfirm(exportUrls, '日历导出本月');

  await requireTestId(page, 'period-export-confirm', '须仍保留 period-export-confirm');
  await requireTestId(
    page,
    'ops-calendar-month-export-confirm',
    '日历导出须出 ops-calendar-month-export-confirm',
  );

  const rows = page.getByTestId('period-export-period-row');
  try {
    await rows.first().waitFor({ state: 'visible', timeout: 15000 });
  } catch {
    throw new Error('多周期须见 period-export-period-row，禁止无 periodId 把条数打成 0');
  }
  if ((await rows.count()) < 2) {
    throw new Error(`多周期须按周期列出，行数须=周期数。实际 ${await rows.count()}`);
  }
  const rowText = await rows.allInnerTexts();
  const blob = rowText.join('\n');
  if (!/3/.test(blob) || !/4/.test(blob)) {
    throw new Error(`多周期各自需关注条数须可见（夹具 3 与 4），禁止全 0。实际：${blob}`);
  }
  if (!/已入账/.test(blob) || !/未入账/.test(blob)) {
    throw new Error(`每周期须见已入账/未入账。实际：${blob}`);
  }

  await requireTestId(page, 'period-export-attention-count', '须见 period-export-attention-count');
  await requireTestId(page, 'period-export-adj-booked', '须见 period-export-adj-booked');
  await requireTestId(page, 'period-export-adj-unbooked', '须见 period-export-adj-unbooked');
  await requireTestId(page, 'period-export-adj-annotation', '须见 period-export-adj-annotation');
  const ann = await page.getByTestId('period-export-adj-annotation').first().innerText();
  if (!/该骑手该日存在需关注订单/.test(ann)) {
    throw new Error(`period-export-adj-annotation 须含「该骑手该日存在需关注订单」：${ann}`);
  }

  const toggle = page.getByTestId('period-export-exclude-toggle');
  await toggle.waitFor({ state: 'visible', timeout: 10000 });
  const excludeOn =
    (await toggle.getAttribute('aria-checked')) === 'true' ||
    (await toggle.isChecked().catch(() => false));
  if (excludeOn) throw new Error('period-export-exclude-toggle 默认必须关闭');
  const adjToggle = page.getByTestId('period-export-adj-sync-toggle');
  await adjToggle.waitFor({ state: 'visible', timeout: 10000 });
  const adjOn =
    (await adjToggle.getAttribute('aria-checked')) === 'true' ||
    (await adjToggle.isChecked().catch(() => false));
  if (adjOn) throw new Error('period-export-adj-sync-toggle 默认必须关闭');
  const admit = page.getByTestId('period-export-admit-attention');
  if (await admit.isVisible().catch(() => false)) {
    const admitText = await admit.innerText();
    if (!CONTAINS_ATTENTION_COPY.test(admitText)) {
      throw new Error(`不排除时须承认「本文件含需关注」：${admitText}`);
    }
  }

  const copy = await page.getByTestId('period-export-confirm').innerText();
  helpers.assertNoPaymentTaxCopy(copy);
  // 允许中文声明「不是打款文件」；禁止正面冒充打款/代发/个税（同 Cycle 2/3 LIVE）
  if (/银行代发|个税/.test(copy) || (/打款文件/.test(copy) && !/不是打款文件/.test(copy))) {
    throw new Error('应发导出不得冒充打款文件');
  }

  await page.getByRole('button', { name: /确认导出/ }).first().click();
  await page.waitForTimeout(800);
  const ids = new Set(
    exportUrls.map((url) => url.match(/\/periods\/(\d+)\/export/)?.[1]).filter(Boolean),
  );
  if (ids.size !== 2) {
    throw new Error(`确认后下载文件数须=周期数 2。实际 ${ids.size}：${exportUrls.join(' | ') || '(无)'}`);
  }
  if (exportUrls.find((url) => queryOf(url).get('exclude_attention') === 'true')) {
    throw new Error('默认不排除订单');
  }
  if (exportUrls.find((url) => queryOf(url).get('exclude_attention_adjustments') === 'true')) {
    throw new Error('默认不排除奖惩');
  }

  await helpers.shot(page, 'cdp-ops-calendar-month-export-confirm');
}

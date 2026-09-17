/** CDP: ops-export-attention-parity — 导出确认框与需关注同源；默认不排除；排除落行等后端 */
import { siteLevelOpenPeriod } from '../cycle1-lib.mjs';
import {
  ATTENTION_ORDER_NOS,
  CONTAINS_ATTENTION_COPY,
  attentionOrders,
  clickPeriodExport,
  dashboardAttentionCount,
  exportPeriodBlob,
  parseIntText,
  siteMonth,
  xlsxContainsOrderNo,
} from '../cycle2-lib.mjs';

export const name = 'ops-export-attention-parity';

function excludeFlagFromUrl(url) {
  try {
    const parsed = new URL(url);
    const raw = parsed.searchParams.get('exclude_attention');
    if (raw == null) return null;
    return /^(1|true|yes)$/i.test(raw);
  } catch {
    return /exclude_attention=(1|true)/i.test(url);
  }
}

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();

  const orders = await attentionOrders({ apiUrl: config.apiUrl, token, siteId, month });
  const nos = new Set(orders.map((row) => row.order_no));
  const missing = ATTENTION_ORDER_NOS.filter((no) => !nos.has(no));
  if (missing.length) {
    throw new Error(
      `夹具需关注单未进 attention 谓词（abnormal ∪ 退款 ∪ 时长>60 的 completed）：${missing.join('、')}。请先 seed`,
    );
  }
  const dash = await dashboardAttentionCount({ apiUrl: config.apiUrl, token, siteId, month });
  const attentionCount = orders.length;
  if (Number.isFinite(dash.count) && dash.count > 0 && dash.count < attentionCount) {
    throw new Error(
      `工作台需关注条数(${dash.count})与订单 attention 列表(${attentionCount})不同源`,
    );
  }

  const period = await siteLevelOpenPeriod({ apiUrl: config.apiUrl, token, siteId, month });
  if (!period?.id) throw new Error('本站无开放周期，无法测应发导出');

  const included = await exportPeriodBlob({
    apiUrl: config.apiUrl,
    token,
    periodId: period.id,
    excludeAttention: false,
  });
  if (!included.res.ok) {
    throw new Error(`导出（不排除）失败 HTTP ${included.res.status}`);
  }

  const excluded = await exportPeriodBlob({
    apiUrl: config.apiUrl,
    token,
    periodId: period.id,
    excludeAttention: true,
  });
  if (excluded.res.status === 422) {
    throw new Error(
      `导出 exclude_attention=true 被 422。后端 Must 2 须接受该查询参数（落行过滤仍可后补）`,
    );
  }
  if (!excluded.res.ok && excluded.res.status !== 404 && excluded.res.status !== 501) {
    throw new Error(`导出 exclude_attention=true HTTP ${excluded.res.status}（参数应可传）`);
  }
  if (excluded.res.ok) {
    const leaked = ATTENTION_ORDER_NOS.filter((no) => xlsxContainsOrderNo(excluded.buf, no));
    if (leaked.length) {
      console.warn(
        `exclude_attention 落行等后端：文件仍含 ${leaked.join('、')}（只影响文件行，不改 gross/net）`,
      );
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
      headers: { 'content-disposition': 'attachment; filename="cycle2-export.xlsx"' },
    });
  });

  await page.goto(
    `${config.adminUrl}/rider-salary/period?site_id=${siteId}&month=${month}&id=${period.id}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await clickPeriodExport(page, period);

  const box = page.getByTestId('period-export-confirm');
  try {
    await box.waitFor({ state: 'visible', timeout: 20000 });
  } catch {
    throw new Error('未见 period-export-confirm。导出须先出确认框，不得直接下载');
  }

  const countEl = page.getByTestId('period-export-attention-count');
  await countEl.waitFor({ state: 'visible', timeout: 15000 });
  const countText = await countEl.innerText();
  if (!/本周期需关注订单/.test(countText) || !/\d+/.test(countText)) {
    throw new Error(`period-export-attention-count 须含「本周期需关注订单 N 条」：${countText}`);
  }
  const uiCount = parseIntText(countText);
  if (
    Number.isFinite(uiCount) &&
    uiCount !== attentionCount &&
    !(Number.isFinite(dash.count) && uiCount === dash.count)
  ) {
    throw new Error(
      `period-export-attention-count=${uiCount} 与 attention 列表 ${attentionCount} / 工作台 ${dash.count} 不一致`,
    );
  }

  const toggle = page.getByTestId('period-export-exclude-toggle');
  await toggle.waitFor({ state: 'visible', timeout: 10000 });
  const checked =
    (await toggle.getAttribute('aria-checked')) === 'true' ||
    (await toggle.isChecked().catch(() => false));
  if (checked) {
    throw new Error('period-export-exclude-toggle 默认必须关闭');
  }

  const admit = page.getByTestId('period-export-admit-attention');
  await admit.waitFor({ state: 'visible', timeout: 10000 });
  const admitText = await admit.innerText();
  if (!CONTAINS_ATTENTION_COPY.test(admitText)) {
    throw new Error(`不排除时 period-export-admit-attention 须承认「本文件含需关注」：${admitText}`);
  }

  const copy = await box.innerText();
  helpers.assertNoPaymentTaxCopy(copy);
  if (/银行代发|打款文件|个税/.test(copy)) {
    throw new Error('应发导出不得冒充打款文件');
  }

  const confirmBtn = page.getByRole('button', { name: /确认导出/ }).first();
  await confirmBtn.waitFor({ state: 'visible', timeout: 10000 });
  await confirmBtn.click();
  await page.waitForTimeout(400);
  const first = exportUrls[0];
  if (!first) {
    throw new Error('确认导出后未见 /periods/{id}/export 请求');
  }
  if (excludeFlagFromUrl(first) === true) {
    throw new Error(`默认不排除时请求不得带 exclude_attention=true：${first}`);
  }

  await clickPeriodExport(page, period);
  await box.waitFor({ state: 'visible', timeout: 15000 });
  await page.getByTestId('period-export-exclude-toggle').click();
  const onNow =
    (await page.getByTestId('period-export-exclude-toggle').getAttribute('aria-checked')) ===
      'true' ||
    (await page.getByTestId('period-export-exclude-toggle').isChecked().catch(() => false));
  if (!onNow) {
    throw new Error('打开排除开关后 period-export-exclude-toggle 应为开');
  }
  if (await page.getByTestId('period-export-admit-attention').isVisible().catch(() => false)) {
    throw new Error('排除打开后不得再显示 period-export-admit-attention 承认句');
  }
  await page.getByRole('button', { name: /确认导出/ }).first().click();
  await page.waitForTimeout(400);
  const second = exportUrls.find((url) => excludeFlagFromUrl(url) === true);
  if (!second) {
    throw new Error(
      `排除开关打开后请求须带 exclude_attention=true。实际：${exportUrls.join(' | ') || '(无)'}`,
    );
  }

  await helpers.shot(page, 'cdp-ops-export-attention-parity');
}

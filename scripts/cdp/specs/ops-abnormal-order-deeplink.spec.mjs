/** CDP: ops-abnormal-order-deeplink — 异常订单行落到该单 */
import {
  ABNORMAL_BLOCK_TITLE,
  FIXTURE_ABNORMAL_ID,
  FIXTURE_ABNORMAL_NO,
  MUST3_HOOKS,
  MUST3_LANDING_HOOKS,
  assertAbnormalRowOpensThis,
  assertAbnormalViewAllScoped,
  assertLockedGoldUnchanged,
  expandPanel,
  fetchDashboardSummary,
  requireAnyTestId,
  requireHooks,
  requireTestId,
  siteMonth,
  waitPath,
} from '../cycle14-lib.mjs';

export const name = 'ops-abnormal-order-deeplink';

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();

  const summary = await fetchDashboardSummary(config.apiUrl, token, { siteId, month });
  const live = (summary?.attention || []).find((row) => row.key === 'abnormal_orders');
  const liveItem = (live?.items || []).find((row) => row.id || row.order_no) || live?.items?.[0];
  const orderId = Number(liveItem?.id) || FIXTURE_ABNORMAL_ID;
  const orderNo = String(liveItem?.order_no || FIXTURE_ABNORMAL_NO);

  await page.route('**/api/v1/rider-salary/dashboard/summary**', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    const res = await route.fetch();
    const json = await res.json();
    const data = json?.data || {};
    const attention = Array.isArray(data.attention) ? [...data.attention] : [];
    const block = {
      key: 'abnormal_orders',
      title: ABNORMAL_BLOCK_TITLE,
      count: Math.max(Number(live?.count) || 1, 1),
      link: '/rider-salary/order?attention=1',
      items: [
        {
          id: orderId,
          order_no: orderNo,
          rider_id: liveItem?.rider_id || 1,
          rider_name: liveItem?.rider_name || '夹具骑手',
          status: liveItem?.status || 'abnormal',
          duration_min: liveItem?.duration_min || 90,
        },
      ],
    };
    const idx = attention.findIndex((row) => row.key === 'abnormal_orders');
    if (idx >= 0) attention[idx] = block;
    else attention.push(block);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...json, data: { ...data, attention } }),
    });
  });

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await expandPanel(page, ABNORMAL_BLOCK_TITLE);
  await requireHooks(
    page,
    MUST3_HOOKS,
    '未见 ops-abnormal-order-deeplink / dashboard-abnormal-row / dashboard-abnormal-view-all。点行无反应 / 不带 id = FAIL，不得 skip',
  );

  const viewAll = page.getByTestId('dashboard-abnormal-view-all').first();
  await viewAll.click();
  const viewUrl = await waitPath(page, /\/rider-salary\/order/, 20000);
  assertAbnormalViewAllScoped(viewUrl, { siteId, month });
  if (/[?&]status=abnormal(?:&|$)/.test(viewUrl) && !/[?&]attention=1(?:&|$)/.test(viewUrl)) {
    throw new Error('查看全部不得只抛 status=abnormal。改 attention 谓词 = 本席 FAIL');
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await expandPanel(page, ABNORMAL_BLOCK_TITLE);
  await requireTestId(page, 'dashboard-abnormal-row', '异常订单行钩子缺失即红，不得 skip');
  const row = page.getByTestId('dashboard-abnormal-row').first();
  const rowId = (await row.getAttribute('data-order-id')) || String(orderId);
  const rowNo = (await row.getAttribute('data-order-no')) || orderNo;
  if (!rowId && !rowNo) {
    throw new Error('dashboard-abnormal-row 须带 data-order-id 或 data-order-no。不带 id/order_no = FAIL');
  }
  await row.click();
  const rowUrl = await waitPath(page, /\/rider-salary\/order/, 20000);
  assertAbnormalRowOpensThis(rowUrl, { id: rowId, orderNo: rowNo });
  await requireAnyTestId(
    page,
    MUST3_LANDING_HOOKS,
    '落地须打开该单抽屉或列表定位到该 id（order-detail-open / order-row-active）。进月窗全量且无该单打开 = FAIL，不得 skip',
  );

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-abnormal-order-deeplink');
}

/** CDP: ops-resigned-order-deeplink — 离职仍有本月订单行必须落到该骑手 */
import {
  FIXTURE_RESIGNED_JOB,
  FIXTURE_RESIGNED_NAME,
  FIXTURE_RESIGNED_RIDER_ID,
  MUST1_HOOKS,
  MUST1_LANDING_HOOKS,
  MUST1_VIEW_ALL_HOOKS,
  RESIGNED_BLOCK_TITLE,
  assertLockedGoldUnchanged,
  assertResignedRowOpensThis,
  assertResignedViewAllScoped,
  expandPanel,
  fetchDashboardSummary,
  requireAnyTestId,
  requireHooks,
  requireTestId,
  siteMonth,
  waitPath,
} from '../cycle15-lib.mjs';

export const name = 'ops-resigned-order-deeplink';

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();

  const summary = await fetchDashboardSummary(config.apiUrl, token, { siteId, month });
  const live = (summary?.attention || []).find((row) => row.key === 'resigned_with_orders');
  const liveItem = (live?.items || []).find((row) => row.rider_id) || live?.items?.[0];
  const riderId = Number(liveItem?.rider_id) || FIXTURE_RESIGNED_RIDER_ID;
  const riderName = String(liveItem?.name || FIXTURE_RESIGNED_NAME);
  const jobNo = String(liveItem?.job_no || FIXTURE_RESIGNED_JOB);

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
      key: 'resigned_with_orders',
      title: RESIGNED_BLOCK_TITLE,
      count: Math.max(Number(live?.count) || 1, 1),
      link: `/rider-salary/rider?status=resigned&site_id=${siteId}&month=${month}`,
      items: [
        {
          rider_id: riderId,
          job_no: jobNo,
          name: riderName,
          order_count: liveItem?.order_count || 3,
        },
      ],
    };
    const idx = attention.findIndex((row) => row.key === 'resigned_with_orders');
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
  await expandPanel(page, RESIGNED_BLOCK_TITLE);
  await requireHooks(
    page,
    MUST1_HOOKS,
    '未见 ops-resigned-order-deeplink / dashboard-resigned-row / dashboard-resigned-view-all。点行无反应 / 不带 rider_id = FAIL，不得 skip',
  );

  const viewAll = page.getByTestId('dashboard-resigned-view-all').first();
  await viewAll.click();
  const viewUrl = await waitPath(page, /\/rider-salary\/rider/, 20000);
  assertResignedViewAllScoped(viewUrl, { siteId, month });
  await requireAnyTestId(
    page,
    MUST1_VIEW_ALL_HOOKS,
    '查看全部落地须是离职名单范围（rider-list-resigned-scope）。已选站必须带当前 site_id+month。不得 skip',
  );

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await expandPanel(page, RESIGNED_BLOCK_TITLE);
  await requireTestId(page, 'dashboard-resigned-row', '离职仍有本月订单行钩子缺失即红，不得 skip');
  const row = page.getByTestId('dashboard-resigned-row').first();
  const rowRiderId = (await row.getAttribute('data-rider-id')) || String(riderId);
  if (!rowRiderId) {
    throw new Error('dashboard-resigned-row 须带 data-rider-id。不带 rider_id = FAIL');
  }
  await row.click();
  const rowUrl = await waitPath(page, /\/rider-salary\/(rider|order)/, 20000);
  assertResignedRowOpensThis(rowUrl, { riderId: rowRiderId, month, riderName });
  await requireAnyTestId(
    page,
    MUST1_LANDING_HOOKS,
    '落地须打开该骑手档案或该骑手本月订单（rider-profile-open / order-rider-month-scope / rider-row-active）。进离职总名单且无该人打开 / 进整站订单却无该骑手/无该月 = FAIL，不得 skip',
  );
  const landing = await page.locator('body').innerText();
  if (!landing.includes(riderName) && !landing.includes(jobNo) && !landing.includes(String(rowRiderId))) {
    throw new Error('落地须能认出是这一人（姓名或工号）。落到别人 = FAIL');
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-resigned-order-deeplink');
}

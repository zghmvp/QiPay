/** CDP: ops-advance-todo-deeplink — 预支待办行带该条 id；查看全部带当前站月 */
import {
  ADVANCE_PENDING_TITLE,
  MUST3_HOOKS,
  assertAdvanceRowOpensThis,
  assertAdvanceViewAllScoped,
  assertLockedGoldUnchanged,
  expandPanel,
  fetchDashboardSummary,
  requireHooks,
  requireTestId,
  siteMonth,
  waitPath,
} from '../cycle13-lib.mjs';

export const name = 'ops-advance-todo-deeplink';

const FAKE_ADVANCE_ID = 881301;

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();

  const summary = await fetchDashboardSummary(config.apiUrl, token, { siteId, month });
  const live = (summary?.attention || []).find((row) => row.key === 'pending_advances');
  const liveItem = (live?.items || []).find((row) => row.id) || live?.items?.[0];
  const advanceId = Number(liveItem?.id) || FAKE_ADVANCE_ID;

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
      key: 'pending_advances',
      title: ADVANCE_PENDING_TITLE,
      count: Math.max(Number(live?.count) || 1, 1),
      link: '/rider-salary/advance?status=pending',
      items: [
        {
          id: advanceId,
          rider_id: liveItem?.rider_id || 1,
          rider_name: liveItem?.rider_name || '夹具骑手',
          amount: liveItem?.amount || '100.00',
          submit_time: liveItem?.submit_time || `${month}-10T10:00:00`,
        },
      ],
    };
    const idx = attention.findIndex((row) => row.key === 'pending_advances');
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
  const body = await page.locator('body').innerText();
  if (!body.includes(ADVANCE_PENDING_TITLE)) {
    throw new Error(`工作台未见「${ADVANCE_PENDING_TITLE}」，不得 skip`);
  }
  await expandPanel(page, ADVANCE_PENDING_TITLE);
  await requireHooks(
    page,
    MUST3_HOOKS,
    '未见 ops-advance-todo-deeplink / dashboard-advance-row / dashboard-advance-view-all，不得 skip',
  );

  const viewAll = page.getByTestId('dashboard-advance-view-all').first();
  await viewAll.click();
  const viewUrl = await waitPath(page, /\/rider-salary\/advance/, 20000);
  assertAdvanceViewAllScoped(viewUrl, { siteId, month });

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await expandPanel(page, ADVANCE_PENDING_TITLE);
  await requireTestId(page, 'dashboard-advance-row', '预支待办行钩子缺失即红，不得 skip');
  const row = page.getByTestId('dashboard-advance-row').first();
  const rowId = await row.getAttribute('data-advance-id');
  if (!rowId) {
    throw new Error('dashboard-advance-row 须带 data-advance-id，点行不像办这一条 = FAIL');
  }
  await row.click();
  const rowUrl = await waitPath(page, /\/rider-salary\/advance/, 20000);
  assertAdvanceRowOpensThis(rowUrl, rowId);
  const landing = page.getByTestId('advance-detail-open').or(page.getByTestId('advance-row-active'));
  const opened = await landing.first().isVisible().catch(() => false);
  if (!opened && !new URL(rowUrl, 'http://127.0.0.1').searchParams.get('id')) {
    throw new Error('落地须打开该条或列表定位到该 id。进总列表且无该条打开 = FAIL');
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-advance-todo-deeplink');
}

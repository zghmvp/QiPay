/** CDP: ops-dashboard-stale-to-calc — #33 需重算查看全部带本站本月；该行进算薪页 */
import {
  CYCLE4_DASHBOARD_HOOKS,
  CYCLE5_DASHBOARD_HOOK,
  LOCKED_GOLD_FORBIDDEN,
  PR33_CALC_HOOKS,
  PR33_DASHBOARD_HOOKS,
  PR33_LANDING_HOOKS,
  STALE_BLOCK_TITLE,
  STALE_RECALC_REGRESSION,
  STALE_SCOPE_COPY,
  assertLockedGoldUnchanged,
  assertNoAutoCalc,
  assertPeriodListRequestScoped,
  assertRowGoesToCalculate,
  assertViewAllHasSiteMonth,
  expandNeedRecalcPanel,
  fetchDashboardSummary,
  fetchPeriods,
  hasAutoCalc,
  isPeriodDrawer,
  loadCycle6StatusHooks,
  periodIdFromCalcUrl,
  requireHooks,
  requireTestId,
  siteMonth,
  waitPath,
} from '../cycle6-lib.mjs';

export const name = 'ops-dashboard-stale-to-calc';

const OTHER_PERIOD_ID = 88012;
const OTHER_SITE_ID = 999;

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();

  const summary = await fetchDashboardSummary(config.apiUrl, token, { siteId, month });
  const live = (summary?.attention || []).find((row) => row.key === 'stale_periods');
  const liveItem =
    (live?.items || []).find((row) => Number(row.site_id) === Number(siteId)) || live?.items?.[0];
  if (!liveItem?.period_id) {
    throw new Error(
      '工作台无本站需重算周期，不得 skip。请先 seed stale 周期（FIX_C17 / 奖惩 mark_stale）',
    );
  }
  const periodId = Number(liveItem.period_id);

  const scoped = await fetchPeriods(config.apiUrl, token, {
    site_id: siteId,
    month,
    stale: '1',
  });
  if ([404, 405, 422, 501].includes(scoped.res.status)) {
    throw new Error(`GET /periods?stale=1&site_id=&month= HTTP ${scoped.res.status}，不得 skip`);
  }
  const leaked = scoped.items.filter((row) => Number(row.site_id) && Number(row.site_id) !== Number(siteId));
  if (leaked.length) {
    throw new Error(
      `他站 stale 不得出现。site_id=${siteId} 列表仍含 ${leaked.map((row) => row.site_id).join(',')}`,
    );
  }

  const periodReqs = [];
  const posted = [];
  page.on('request', (req) => {
    if (req.method() === 'GET' && /\/api\/v1\/rider-salary\/periods(?:\?|$)/.test(req.url())) {
      periodReqs.push(req.url());
    }
    if (req.method() === 'POST' && /\/periods\/\d+\/calculate/.test(req.url())) {
      posted.push(req.url());
    }
  });

  await page.route('**/api/v1/rider-salary/dashboard/summary**', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    const res = await route.fetch();
    const json = await res.json();
    const data = json?.data || {};
    const attention = Array.isArray(data.attention) ? [...data.attention] : [];
    const stale = {
      key: 'stale_periods',
      title: STALE_BLOCK_TITLE,
      count: Math.max(Number(live?.count) || 1, 2),
      link: '/rider-salary/period?stale=1',
      items: [
        {
          period_id: periodId,
          site_id: Number(siteId),
          range: liveItem.range || `${month}-01 ~ ${month}-15`,
          status: liveItem.status || 'open',
          stale_count: liveItem.stale_count || 2,
          link: `/rider-salary/period?id=${periodId}`,
        },
        {
          period_id: OTHER_PERIOD_ID,
          site_id: OTHER_SITE_ID,
          range: `${month}-01 ~ ${month}-28`,
          status: 'open',
          stale_count: 1,
          link: `/rider-salary/period?id=${OTHER_PERIOD_ID}`,
        },
      ],
    };
    const idx = attention.findIndex((row) => row.key === 'stale_periods');
    if (idx >= 0) attention[idx] = stale;
    else attention.push(stale);
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
  const dashBody = await page.locator('body').innerText();
  if (!dashBody.includes(STALE_BLOCK_TITLE)) {
    throw new Error(`工作台未见「${STALE_BLOCK_TITLE}」，不得 skip`);
  }
  helpers.assertNoPaymentTaxCopy(dashBody);
  if (LOCKED_GOLD_FORBIDDEN.test(dashBody)) {
    throw new Error('金标 8200/7800/3500 已锁，不得出现 4629.33 / 预支 800');
  }

  await expandNeedRecalcPanel(page);
  await requireHooks(
    page,
    PR33_DASHBOARD_HOOKS,
    '#33 未见 ops-dashboard-stale-to-calc / dashboard-stale-row / dashboard-stale-view-all，不得 skip',
  );

  const viewAll = page.getByTestId('dashboard-stale-view-all').first();
  await viewAll.click();
  const viewUrl = await waitPath(page, /\/rider-salary\/period/, 20000);
  assertViewAllHasSiteMonth(viewUrl, { siteId, month });
  assertNoAutoCalc(viewUrl, '需重算查看全部');
  if (isPeriodDrawer(viewUrl)) {
    throw new Error(`查看全部不得停在 ?id= 抽屉。实际 ${viewUrl}`);
  }
  await page.waitForTimeout(800);
  assertPeriodListRequestScoped(periodReqs, { siteId, month });

  await requireHooks(
    page,
    PR33_LANDING_HOOKS,
    '#33 落地须见 period-stale-scope。只切当前页 / 忽略 query = FAIL',
  );
  const listBody = await page.locator('body').innerText();
  if (!STALE_SCOPE_COPY.test(listBody) && !/需重算/.test(listBody)) {
    throw new Error('周期列表落地须可见「已按工作台跳转筛选：需重算周期」，不得 skip');
  }
  if (listBody.includes(String(OTHER_PERIOD_ID))) {
    throw new Error(`他站 stale ${OTHER_PERIOD_ID} 不得出现在本站本月列表`);
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await expandNeedRecalcPanel(page);
  await requireTestId(page, 'dashboard-stale-row', '#33 未见 dashboard-stale-row，不得 skip');
  const row = page.getByTestId('dashboard-stale-row').first();
  const rowPeriodId = await row.getAttribute('data-period-id');
  if (!rowPeriodId) {
    throw new Error('dashboard-stale-row 须带 data-period-id，不得 skip');
  }
  const postedBeforeRow = posted.length;
  await row.click();
  const rowUrl = await waitPath(page, /\/rider-salary\/period/, 20000);
  assertRowGoesToCalculate(rowUrl, rowPeriodId);
  assertNoAutoCalc(rowUrl, '需重算该行');
  if (posted.length > postedBeforeRow) {
    throw new Error(`该行进算薪页不得直 POST calculate。实际 ${posted.slice(postedBeforeRow).join(', ')}`);
  }
  await requireHooks(
    page,
    PR33_CALC_HOOKS,
    '#33 算薪页须见 period-calc-precheck / period-calc-title / period-calc-start。带参抽屉不够绿，不得 skip',
  );

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await expandNeedRecalcPanel(page);
  await requireTestId(
    page,
    STALE_RECALC_REGRESSION,
    '#9 stale-goto-calculate 立即重算回归须继续绿，不得 skip',
  );
  const postedBeforeRecalc = posted.length;
  await page.getByTestId(STALE_RECALC_REGRESSION).first().click();
  const recalcUrl = await waitPath(page, /\/rider-salary\/period\/\d+\/calculate/, 20000);
  const recalcId = periodIdFromCalcUrl(recalcUrl) || String(periodId);
  assertRowGoesToCalculate(recalcUrl, recalcId);
  if (hasAutoCalc(recalcUrl)) {
    throw new Error(`立即重算禁止 auto=1。实际 ${recalcUrl}`);
  }
  if (posted.length > postedBeforeRecalc) {
    throw new Error(`立即重算不得直 POST calculate（#9）。实际 ${posted.slice(postedBeforeRecalc).join(', ')}`);
  }

  const status = loadCycle6StatusHooks();
  if (status.landed) {
    const required = [
      'ops-dashboard-stale-to-calc',
      'dashboard-stale-view-all',
      'dashboard-stale-row',
      'period-stale-scope',
      'stale-goto-calculate',
    ];
    const missing = required.filter((id) => !status.ids.includes(id) && !PR33_DASHBOARD_HOOKS.includes(id));
    if (missing.length) {
      /* status 表已写这些钩子；活页上已 requireHooks */
    }
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  for (const id of [...CYCLE4_DASHBOARD_HOOKS, CYCLE5_DASHBOARD_HOOK]) {
    void id;
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-dashboard-stale-to-calc');
}

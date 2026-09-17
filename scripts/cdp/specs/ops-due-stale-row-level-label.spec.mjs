/** CDP: ops-due-stale-row-level-label — 倒计时 / 需重算行必须分清站点级 vs 骑手级
 * 两行只有同一段 range、都无级别/骑手名，或点行落到另一条 period_id = FAIL。
 */
import {
  DUE_BLOCK_TITLE,
  FIXTURE_RANGE,
  FIXTURE_RIDER_JOB,
  FIXTURE_RIDER_NAME,
  FIXTURE_RIDER_PERIOD_ID,
  FIXTURE_SITE_PERIOD_ID,
  MUST1_HOOKS,
  STALE_BLOCK_TITLE,
  assertDueKeepsPeriodId,
  assertDueStaleLevelLabels,
  assertLockedGoldUnchanged,
  assertStaleKeepsPeriodId,
  expandPanel,
  fetchDashboardSummary,
  landingPeriodId,
  requireHooks,
  requireTestId,
  siteMonth,
  waitPath,
} from '../cycle14-lib.mjs';

export const name = 'ops-due-stale-row-level-label';

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();

  const summary = await fetchDashboardSummary(config.apiUrl, token, { siteId, month });
  const liveDue = (summary?.attention || []).find((row) => row.key === 'due_periods');
  const liveStale = (summary?.attention || []).find((row) => row.key === 'stale_periods');
  const sitePeriodId =
    Number(
      (liveDue?.items || []).find((row) => Number(row.rider_id) === 0)?.period_id,
    ) || FIXTURE_SITE_PERIOD_ID;
  const riderPeriodId =
    Number(
      (liveDue?.items || liveStale?.items || []).find((row) => Number(row.rider_id) > 0)
        ?.period_id,
    ) || FIXTURE_RIDER_PERIOD_ID;
  const riderName =
    (liveDue?.items || liveStale?.items || []).find((row) => Number(row.rider_id) > 0)
      ?.rider_name ||
    (liveDue?.items || liveStale?.items || []).find((row) => Number(row.rider_id) > 0)
      ?.name ||
    FIXTURE_RIDER_NAME;

  await page.route('**/api/v1/rider-salary/dashboard/summary**', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    const res = await route.fetch();
    const json = await res.json();
    const data = json?.data || {};
    const attention = Array.isArray(data.attention) ? [...data.attention] : [];
    const pair = [
      {
        period_id: sitePeriodId,
        site_id: Number(siteId),
        rider_id: 0,
        range: FIXTURE_RANGE,
        status: 'open',
        end_date: `${month}-15`,
        days_left: 1,
        stale_count: 2,
        level: 'site',
      },
      {
        period_id: riderPeriodId,
        site_id: Number(siteId),
        rider_id: 18,
        rider_name: riderName,
        job_no: FIXTURE_RIDER_JOB,
        name: riderName,
        range: FIXTURE_RANGE,
        status: 'open',
        end_date: `${month}-15`,
        days_left: 1,
        stale_count: 1,
        level: 'rider',
      },
    ];
    const dueBlock = {
      key: 'due_periods',
      title: '即将到期周期',
      count: 2,
      link: '/rider-salary/period?status=open',
      items: pair,
    };
    const staleBlock = {
      key: 'stale_periods',
      title: '需重算周期',
      count: 2,
      link: '/rider-salary/period?status=open&stale=1',
      items: pair,
    };
    const dueIdx = attention.findIndex((row) => row.key === 'due_periods');
    if (dueIdx >= 0) attention[dueIdx] = dueBlock;
    else attention.push(dueBlock);
    const staleIdx = attention.findIndex((row) => row.key === 'stale_periods');
    if (staleIdx >= 0) attention[staleIdx] = staleBlock;
    else attention.push(staleBlock);
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
  await expandPanel(page, DUE_BLOCK_TITLE);
  await expandPanel(page, STALE_BLOCK_TITLE);
  await requireHooks(
    page,
    MUST1_HOOKS,
    '未见 ops-due-stale-row-level-label / dashboard-due-row / dashboard-stale-row / dashboard-row-level / dashboard-row-rider-name。两行只有同一段 range、都无级别/骑手名 = FAIL，不得 skip',
  );

  const siteRow = page
    .locator('[data-testid="dashboard-due-row"][data-row-level="site"]')
    .or(page.locator('[data-testid="dashboard-due-row"][data-rider-id="0"]'))
    .first();
  const riderRow = page
    .locator('[data-testid="dashboard-due-row"][data-row-level="rider"]')
    .or(page.locator('[data-testid="dashboard-due-row"][data-rider-id]:not([data-rider-id="0"])'))
    .first();
  await siteRow.waitFor({ state: 'visible', timeout: 15000 });
  await riderRow.waitFor({ state: 'visible', timeout: 15000 });
  const siteText = `${await siteRow.innerText()} ${await page.getByTestId('dashboard-row-level').first().innerText()}`;
  const riderText = `${await riderRow.innerText()} ${await page.getByTestId('dashboard-row-rider-name').first().innerText()}`;
  assertDueStaleLevelLabels({ siteText, riderText, riderName });

  const sitePeriod = (await siteRow.getAttribute('data-period-id')) || String(sitePeriodId);
  await siteRow.click();
  const dueUrl = await waitPath(page, /\/rider-salary\/period/, 20000);
  assertDueKeepsPeriodId(dueUrl, sitePeriod);
  if (landingPeriodId(dueUrl) !== String(sitePeriod)) {
    throw new Error(`倒计时点行落到另一条 period_id = FAIL。期望 ${sitePeriod} 实际 ${dueUrl}`);
  }

  await page.goto(
    `${config.adminUrl}/rider-salary/dashboard?site_id=${siteId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );
  await expandPanel(page, STALE_BLOCK_TITLE);
  await requireTestId(page, 'dashboard-stale-row', '需重算行钩子缺失即红，不得 skip');
  const staleRider = page
    .locator('[data-testid="dashboard-stale-row"][data-row-level="rider"]')
    .or(page.locator('[data-testid="dashboard-stale-row"][data-rider-id]:not([data-rider-id="0"])'))
    .first();
  await staleRider.waitFor({ state: 'visible', timeout: 15000 });
  const stalePeriod =
    (await staleRider.getAttribute('data-period-id')) || String(riderPeriodId);
  await staleRider.click();
  const staleUrl = await waitPath(page, /\/rider-salary\/period\/\d+\/calculate/, 20000);
  assertStaleKeepsPeriodId(staleUrl, stalePeriod);

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-due-stale-row-level-label');
}

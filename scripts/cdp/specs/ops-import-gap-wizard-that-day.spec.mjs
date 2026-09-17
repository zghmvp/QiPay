/** CDP: ops-import-gap-wizard-that-day — 导入缺口行必须打开向导并预填该站该日
 * 必须走工作台「导入覆盖缺口」行 → 向导。只进订单空列表 / 进 /calendar / API importCsv 绿 = FAIL。
 */
import {
  FIXTURE_GAP_DATE,
  GAP_BLOCK_TITLE,
  MUST2_ROW_HOOKS,
  MUST2_WIZARD_HOOKS,
  assertGapOpenedWizardNotOrderList,
  assertLockedGoldUnchanged,
  assertNoImportCsvGreen,
  assertWizardPrefill,
  expandPanel,
  fetchDashboardSummary,
  requireHooks,
  siteMonth,
  waitWizardOpen,
} from '../cycle14-lib.mjs';

export const name = 'ops-import-gap-wizard-that-day';

export async function run({ page, helpers, config }) {
  assertLockedGoldUnchanged();
  assertNoImportCsvGreen();
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();
  const gapDate = process.env.CDP_GAP_DATE || FIXTURE_GAP_DATE;

  const summary = await fetchDashboardSummary(config.apiUrl, token, { siteId, month });
  const live = (summary?.attention || []).find((row) => row.key === 'import_gaps');
  const liveItem =
    (live?.items || []).find((row) => String(row.date || '').endsWith(gapDate.slice(-2))) ||
    (live?.items || [])[0];
  const rowDate = String(liveItem?.date || gapDate);
  const rowSiteId = Number(liveItem?.site_id) || Number(siteId);

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
      key: 'import_gaps',
      title: GAP_BLOCK_TITLE,
      count: Math.max(Number(live?.count) || 1, 1),
      link: '/rider-salary/order',
      items: [
        {
          site_id: rowSiteId,
          site_name: liveItem?.site_name || '夹具站',
          date: rowDate,
        },
      ],
    };
    const idx = attention.findIndex((row) => row.key === 'import_gaps');
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
  await expandPanel(page, GAP_BLOCK_TITLE);
  await requireHooks(
    page,
    MUST2_ROW_HOOKS,
    '未见 ops-import-gap-wizard-that-day / dashboard-import-gap-row。点行无反应 = FAIL，不得 skip。禁止只断言订单列表带日，禁止走 importCsv',
  );

  const row = page.getByTestId('dashboard-import-gap-row').first();
  const attrDate = (await row.getAttribute('data-gap-date')) || rowDate;
  const attrSite = (await row.getAttribute('data-gap-site-id')) || String(rowSiteId);
  await row.click();

  let wizardVisible = false;
  try {
    await waitWizardOpen(page, 15000);
    wizardVisible = true;
  } catch {
    wizardVisible = false;
  }
  assertGapOpenedWizardNotOrderList(page.url(), wizardVisible);
  if (isOrderListOnly(page.url()) && !wizardVisible) {
    throw new Error('只进订单空列表办不了导入 = FAIL。Must 2 必须打开向导并预填该站该日');
  }

  await requireHooks(
    page,
    MUST2_WIZARD_HOOKS,
    '向导钩子缺失即红：import-wizard / import-wizard-site / import-wizard-date-from / import-wizard-date-to。API importCsv 绿替向导 = FAIL，不得 skip',
  );

  const dateFrom =
    (await page.getByTestId('import-wizard-date-from').getAttribute('data-value')) ||
    (await page.getByTestId('import-wizard-date-from').innerText()).trim();
  const dateTo =
    (await page.getByTestId('import-wizard-date-to').getAttribute('data-value')) ||
    (await page.getByTestId('import-wizard-date-to').innerText()).trim();
  const wizardSite =
    (await page.getByTestId('import-wizard-site').getAttribute('data-value')) ||
    (await page.getByTestId('import-wizard-site').innerText()).trim();
  assertWizardPrefill({
    siteId: /^\d+$/.test(wizardSite) ? wizardSite : attrSite,
    date: attrDate,
    dateFrom,
    dateTo,
    selectedSiteId: siteId,
  });
  if (dateFrom !== attrDate || dateTo !== attrDate) {
    throw new Error(
      `向导日期窗必须是该日 ${attrDate}（date_from=date_to）。不带该 date = FAIL。实际 ${dateFrom}~${dateTo}`,
    );
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-import-gap-wizard-that-day');
}

function isOrderListOnly(raw) {
  return /\/rider-salary\/order\/?(\?|$)/.test(raw) && !/import-wizard/.test(raw);
}

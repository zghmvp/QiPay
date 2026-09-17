/** CDP: ops-calendar-no-plan-deeplink */
export const name = 'ops-calendar-no-plan-deeplink';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);

  const siteId = process.env.CDP_SITE_ID || '1';
  const riderId = process.env.CDP_RIDER_ID || '1';
  const month = process.env.CDP_MONTH || '2026-09';

  await page.goto(
    `${config.adminUrl}/rider-salary/calendar?site_id=${siteId}&rider_id=${riderId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );

  const bind = page.getByTestId('calendar-bind-plan').first();
  await bind.waitFor({ state: 'visible', timeout: 30000 });
  await helpers.shot(page, 'cdp-ops-calendar-no-plan-deeplink-cell');
  await bind.click();

  await page.waitForURL(/\/rider-salary\/rider\/\d+/, { timeout: 30000 });
  const url = page.url();
  if (!url.includes(`rider/${riderId}`) && !url.includes(`rider_id=${riderId}`)) {
    // path 形 /rider-salary/rider/{id}
    const m = url.match(/\/rider-salary\/rider\/(\d+)/);
    if (!m) throw new Error(`深链未落到骑手档案：${url}`);
  }
  if (!url.includes('tab=binding')) {
    throw new Error(`深链缺少 tab=binding：${url}`);
  }
  await helpers.shot(page, 'cdp-ops-calendar-no-plan-deeplink-binding');
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
}

/** CDP: ops-calendar-adjust-date-window — 日历录入奖惩按日落地 */
import { FIX_JOB_NO, resolveFixRiderId, siteMonth } from '../cycle1-lib.mjs';

export const name = 'ops-calendar-adjust-date-window';

const DAY = process.env.CDP_ADJUST_DAY || '2026-09-10';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const { siteId, month } = siteMonth();
  const riderId = await resolveFixRiderId(config.apiUrl, admin.access_token, siteId);

  await page.goto(
    `${config.adminUrl}/rider-salary/calendar?site_id=${siteId}&rider_id=${riderId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );

  const cell = page.getByTestId(`calendar-day-${DAY}`).first();
  await cell.waitFor({ state: 'visible', timeout: 30000 });
  await cell.click();

  const cta = page.getByTestId('calendar-go-adjustment');
  await cta.waitFor({ state: 'visible', timeout: 20000 });
  await helpers.shot(page, 'cdp-ops-calendar-adjust-date-window-drawer');
  await cta.click();

  await page.waitForURL(/\/rider-salary\/adjustment/, { timeout: 30000 });
  const url = new URL(page.url());
  const from = url.searchParams.get('date_from');
  const to = url.searchParams.get('date_to');
  const rider = url.searchParams.get('rider_id');
  if (!from || !to) {
    throw new Error(
      `奖惩深链缺少 date_from+date_to（禁止只推不消费的 date）。实际：${url.pathname}${url.search}`,
    );
  }
  if (from !== DAY || to !== DAY) {
    throw new Error(`日期窗须等于该日 ${DAY}，实际 date_from=${from} date_to=${to}`);
  }
  if (String(rider) !== String(riderId)) {
    throw new Error(`奖惩页骑手不符：期望 ${riderId} 实际 ${rider}`);
  }

  const hint = page.getByTestId('adjustment-date-window');
  await hint.waitFor({ state: 'visible', timeout: 20000 });
  const hintText = await hint.innerText();
  if (!hintText.includes(DAY)) {
    throw new Error(`adjustment-date-window 未消费该日：${hintText}`);
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-calendar-adjust-date-window');
  void FIX_JOB_NO;
}

/** CDP: ops-calendar-no-plan-deeplink
 * 必须指向 FIX_C17_R1（有单无方案日）；禁止为过测弱化产品 CTA。
 */
export const name = 'ops-calendar-no-plan-deeplink';

const FIX_JOB_NO = 'FIX_C17_R1';

async function resolveFixRiderId(helpers, config, siteId) {
  if (process.env.CDP_RIDER_ID) return process.env.CDP_RIDER_ID;
  const admin = await helpers.swaggerLogin(config.username, config.password);
  const qs = new URLSearchParams({
    page: '1',
    size: '20',
    site_id: String(siteId),
    keyword: FIX_JOB_NO,
  });
  const res = await fetch(`${config.apiUrl}/api/v1/rider-salary/riders?${qs}`, {
    headers: { Authorization: `Bearer ${admin.access_token}` },
  });
  if (!res.ok) {
    throw new Error(`查找 ${FIX_JOB_NO} 失败：HTTP ${res.status}`);
  }
  const json = await res.json();
  const hit = (json?.data?.items || []).find((r) => r.job_no === FIX_JOB_NO);
  if (!hit) {
    throw new Error(
      `未找到工号 ${FIX_JOB_NO}。请先运行：node scripts/cdp/seed-xiaoxiang-fixtures.mjs`,
    );
  }
  return String(hit.id);
}

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);

  const siteId = process.env.CDP_SITE_ID || '13';
  const month = process.env.CDP_MONTH || '2026-09';
  const riderId = await resolveFixRiderId(helpers, config, siteId);

  await page.goto(
    `${config.adminUrl}/rider-salary/calendar?site_id=${siteId}&rider_id=${riderId}&month=${month}`,
    { waitUntil: 'networkidle', timeout: 60000 },
  );

  const bind = page.getByTestId('calendar-bind-plan').first();
  try {
    await bind.waitFor({ state: 'visible', timeout: 30000 });
  } catch (err) {
    throw new Error(
      `未找到 calendar-bind-plan（去绑方案）。请确认 FIX_C17_R1 在 ${month} 的 9/15–17 为有单无方案日；` +
        `site_id=${siteId} rider_id=${riderId}。勿用全月有绑的灯塔骑手。` +
        ` 原始错误：${err.message}`,
    );
  }
  await helpers.shot(page, 'cdp-ops-calendar-no-plan-deeplink-cell');
  await bind.click();

  await page.waitForURL(/\/rider-salary\/rider\/\d+/, { timeout: 30000 });
  const url = page.url();
  const m = url.match(/\/rider-salary\/rider\/(\d+)/);
  if (!m) throw new Error(`深链未落到骑手档案：${url}`);
  if (m[1] !== String(riderId)) {
    throw new Error(`深链骑手 id 不符：期望 ${riderId}，实际 ${m[1]}，url=${url}`);
  }
  if (!url.includes('tab=binding')) {
    throw new Error(`深链缺少 tab=binding：${url}`);
  }
  await helpers.shot(page, 'cdp-ops-calendar-no-plan-deeplink-binding');
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
}

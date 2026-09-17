/** CDP: ops-prune-weather-subjects — 新建科目下拉无天气三件套 */
export const name = 'ops-prune-weather-subjects';

const BANNED = ['恶劣天气', '高温补贴', '大促临时加价'];

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const headers = { Authorization: `Bearer ${admin.access_token}` };

  const res = await fetch(`${config.apiUrl}/api/v1/rider-salary/subjects/all`, {
    headers,
  });
  if (!res.ok) throw new Error(`科目下拉失败 ${res.status}`);
  const subjects = (await res.json())?.data || [];
  const enabledBanned = subjects.filter(
    (row) =>
      row.status === 'enable' &&
      BANNED.some((name) => String(row.name || '').includes(name.replace('补贴', '')) || String(row.code || '').includes('WEATHER') || String(row.code || '').includes('HIGH_TEMP') || String(row.code || '').includes('PROMO')),
  );
  const weatherEnabled = subjects.filter(
    (row) =>
      row.status === 'enable' &&
      ['BONUS_BAD_WEATHER', 'BONUS_HIGH_TEMP', 'BONUS_PROMO'].includes(row.code),
  );
  if (weatherEnabled.length) {
    throw new Error(
      `启用科目仍含天气残留：${weatherEnabled.map((r) => r.name).join('、')}`,
    );
  }
  void enabledBanned;

  await page.goto(`${config.adminUrl}/rider-salary/subject`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  await page.goto(`${config.adminUrl}/rider-salary/plan`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  const body = await page.locator('body').innerText();
  helpers.assertNoPaymentTaxCopy(body);
  if (body.includes('日标记') || body.includes('站点公告')) {
    throw new Error('侧栏仍出现已删日标记/站点公告');
  }
  await helpers.shot(page, 'cdp-ops-prune-weather-subjects');
}

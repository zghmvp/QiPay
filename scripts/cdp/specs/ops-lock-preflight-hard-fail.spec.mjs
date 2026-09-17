/** CDP: ops-lock-preflight-hard-fail — 有完成单未算出则锁不住 */
export const name = 'ops-lock-preflight-hard-fail';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const headers = {
    Authorization: `Bearer ${admin.access_token}`,
    'Content-Type': 'application/json',
  };
  const siteId = process.env.CDP_SITE_ID || '13';
  const month = process.env.CDP_MONTH || '2026-09';

  const listRes = await fetch(
    `${config.apiUrl}/api/v1/rider-salary/periods?site_id=${siteId}&month=${month}&page=1&size=20`,
    { headers },
  );
  const period = ((await listRes.json())?.data?.items || []).find(
    (row) => row.status === 'open' || row.status === 'reopened',
  );
  if (!period?.id) throw new Error('未找到开放周期，无法验锁账硬拦');

  const lockRes = await fetch(
    `${config.apiUrl}/api/v1/rider-salary/periods/${period.id}/lock`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify({ reason: 'CDP 锁账硬拦' }),
    },
  );
  const lockJson = await lockRes.json();
  const msg = `${lockJson?.msg || ''} ${JSON.stringify(lockJson?.data || {})}`;
  if (lockRes.ok && lockJson?.code === 200) {
    throw new Error('FIX_C17 类有单未算出周期不应锁账成功');
  }
  if (!/锁账中止|无生效方案|未算出|缺送达|从未成功/.test(msg)) {
    throw new Error(`锁账失败文案缺少同口径中文：${msg.slice(0, 300)}`);
  }

  const after = await fetch(
    `${config.apiUrl}/api/v1/rider-salary/periods/${period.id}`,
    { headers },
  );
  const status = (await after.json())?.data?.status;
  if (status === 'locked' || status === 'paid') {
    throw new Error(`锁账被拒绝后状态仍变为 ${status}`);
  }

  await page.goto(`${config.adminUrl}/rider-salary/period`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-lock-preflight-hard-fail');
}

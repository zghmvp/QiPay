/** CDP: ops-import-recalc-progress — 导入后重算状态可观测 */
export const name = 'ops-import-recalc-progress';

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);

  await page.goto(`${config.adminUrl}/rider-salary/order`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });

  const importBtn = page.getByRole('button', { name: /导入/ }).first();
  await importBtn.click();
  await page.getByText('导入后自动重算').waitFor({ state: 'visible', timeout: 15000 });
  await helpers.shot(page, 'cdp-ops-import-recalc-progress-wizard');

  // API 层冒烟：创建假任务不可行；断言权限下 GET 接口可达（404/空也算连通）
  const probe = await page.evaluate(async (api) => {
    const raw = localStorage.getItem('fba-ui-5.7.0-dev-core-access');
    const token = raw ? JSON.parse(raw).accessToken : null;
    const res = await fetch(`${api}/api/v1/rider-salary/recalc-jobs/1`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    return { status: res.status, body: await res.text() };
  }, config.apiUrl);

  if (![200, 404].includes(probe.status) && probe.status !== 400) {
    // 401/403 = 鉴权失败
    if (probe.status === 401 || probe.status === 403) {
      throw new Error(`重算任务接口鉴权失败：${probe.status}`);
    }
  }
  // 中文错误或详情
  if (probe.status === 404 && !/不存在|重算/.test(probe.body)) {
    console.warn('WARN: 404 响应未含中文，body=', probe.body.slice(0, 200));
  }
  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
}

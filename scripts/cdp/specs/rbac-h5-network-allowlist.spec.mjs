import { RBAC, loginAs } from '../rbac-helpers.mjs';

export const name = 'rbac-h5-network-allowlist';

export async function run({ page, helpers, config }) {
  const banned = [];
  page.on('request', (req) => {
    const url = req.url();
    if (/\/api\/v1\/rider-salary\/(orders|engine|import-batches|periods|payrolls)\b/.test(url)) {
      banned.push(url);
    }
  });
  const rd = await loginAs(RBAC.riderUser, RBAC.riderPass);
  await page.goto(`${config.h5Url}/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.evaluate((token) => {
    localStorage.setItem('rider_h5_token', token);
  }, rd.access_token);
  await page.goto(`${config.h5Url}/home`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(1500);
  if (banned.length) {
    throw new Error(`H5 网络出现管理端路径：${banned.join(' | ')}`);
  }
  await helpers.shot(page, 'rbac-h5-network-allowlist', { fullPage: false, optional: true });
}
